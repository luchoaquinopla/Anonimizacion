"""Ejecutor del pipeline: orquesta las etapas end-to-end, aislando el fallo por documento.

Spec `batch-processing`: (1) "Aislamiento de fallos por documento" -- el
fallo de un documento nunca detiene el procesamiento del resto del lote;
(2) "Reintentos ante fallos transitorios" -- solo errores NO tipados
(IO/conexión, nunca `ErrorParseo`) se reintentan, con backoff; (3)
"Trazabilidad sin PII" -- ver `pipeline/resultado.py`, que ya construye por
diseño resúmenes sin PII.

Secuencia por documento (design.md, "Data Flow"):
`extraer -> detectar_tipo -> obtener_parseador+parsear -> [detección de PII
sobre texto libre] -> resolver_claves -> [batch: vincular_episodios] ->
construir_registro -> escribir`. La vinculación de episodios es la única
etapa que opera sobre TODO el lote a la vez (`pseudonimizacion/vinculacion.py`
ya es así desde Fase 6 -- clusteriza por `id_paciente` a través de los
documentos, no puede resolverse documento a documento), por eso
`procesar_lote` primero resuelve cada documento de forma aislada, y recién
vincula episodios sobre los que sobrevivieron, antes de emitir.

Cada etapa concreta se recibe como dependencia inyectable (con default a la
implementación real de la fase correspondiente): esto hace que este módulo
sea testeable con fakes deterministas sin pagar el costo de levantar
`MotorPii` (carga spaCy) o un `Engine` de base de datos real en cada test.

Clasificación de reintentos (design.md, "Aislamiento de fallo y política de
reintentos"): `ErrorParseo` (`dominio/errores.py`) es la jerarquía tipada y
determinística del dominio -- nunca se reintenta, va directo a cuarentena.
Cualquier OTRA excepción (`OSError`, `ConnectionError`, errores de conexión
de SQLAlchemy, etc: fallos de infraestructura, no del contenido del
documento) se considera transitoria y se reintenta hasta `MAX_REINTENTOS`
veces con `BACKOFF_SEGUNDOS`, agotados los cuales se convierte en un
`ErrorParseo(ERROR_TRANSITORIO_AGOTADO)` -- el mensaje crudo de la excepción
original NUNCA se propaga más allá de ese punto (mismo principio que
"Sin PII en cola, logs ni DLQ", design.md).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.deteccion.detector_tipo import detectar_tipo as _detectar_tipo_real
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido, extraer_texto
from anonimizacion.ingesta.artefacto import ArtefactoCrudo
from anonimizacion.parseo.base import ParseadorDocumento
from anonimizacion.parseo.registro import obtener_parseador as _obtener_parseador_real
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pii.politica import clasificar as _clasificar_real
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves
from anonimizacion.pseudonimizacion.resolutor_claves import resolver_claves as _resolver_claves_real
from anonimizacion.pseudonimizacion.vinculacion import DocumentoParaVincular
from anonimizacion.pseudonimizacion.vinculacion import vincular_episodios as _vincular_episodios_real
from anonimizacion.salida.constructor_registro import construir_registro as _construir_registro_real

from .etapas import Etapa
from .resultado import ExitoDocumento, FalloDocumento, ResultadoDocumento

# Backoff exponencial fijo (design.md, tasks.md 9.1): 3 reintentos tras el
# intento inicial -- 4 intentos totales como máximo por documento/etapa.
# `trabajadores/politica_reintentos.py` reusa estas mismas constantes (no se
# duplica el número en dos lugares).
BACKOFF_SEGUNDOS: tuple[int, ...] = (5, 30, 180)
MAX_REINTENTOS = len(BACKOFF_SEGUNDOS)


class DestinoEscritura(Protocol):
    """Lo único que el ejecutor necesita de un destino (`salida/destinos/postgres.py` lo implementa)."""

    def escribir_registro(self, registro: RegistroAnonimizado) -> None: ...


class DestinoCuarentena(Protocol):
    """`salida/cuarentena.py::EscritorCuarentena` implementa esto (Fase 7)."""

    def registrar(self, error: ErrorDocumento) -> None: ...


@dataclass(frozen=True)
class ItemLote:
    """Un documento a procesar: el `id_documento` es externo al `ArtefactoCrudo`.

    Se asigna en la ingesta (ver `trabajadores/tareas.py`, tasks.md 9.2: el
    mensaje de cola es exactamente `{id_documento, uri, sha256}`) -- por eso
    viaja separado, no se deriva del artefacto acá.
    """

    id_documento: str
    artefacto: ArtefactoCrudo


@dataclass(frozen=True)
class _DocumentoResuelto:
    """Documento que ya pasó extracción, parseo y resolución de claves; falta vincular episodio + emitir."""

    id_documento: str
    documento: DocumentoParseado
    claves: ClavesPaciente


def _ejecutar_con_reintentos(
    funcion: Callable[[], object],
    *,
    etapa: str,
    dormir: Callable[[float], None],
) -> object:
    """Ejecuta `funcion`, reintentando solo si lanza algo que NO sea `ErrorParseo`.

    Al agotar los reintentos, la excepción transitoria original se descarta
    y se reemplaza por `ErrorParseo(ERROR_TRANSITORIO_AGOTADO, etapa)` --
    nunca se propaga el mensaje crudo (podría contener detalle de
    infraestructura sensible, y en cualquier caso viola "Sin PII en cola,
    logs ni DLQ" si en algún punto se serializa).
    """
    intento = 0
    while True:
        try:
            return funcion()
        except ErrorParseo:
            raise  # determinístico -- nunca se reintenta
        except Exception:
            if intento >= MAX_REINTENTOS:
                raise ErrorParseo(CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO, etapa=etapa) from None
            dormir(BACKOFF_SEGUNDOS[intento])
            intento += 1


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class EjecutorPipeline:
    """Orquesta el pipeline completo sobre un lote, aislando el fallo por documento."""

    def __init__(
        self,
        *,
        resolutor: ResolutorClaves,
        motor: MotorPii,
        pepper: bytes,
        destino: DestinoEscritura,
        cuarentena: DestinoCuarentena,
        dormir: Callable[[float], None] = time.sleep,
        extraer: Callable[[ArtefactoCrudo], TextoExtraido] = lambda artefacto: extraer_texto(
            Path(artefacto.uri)
        ),
        detectar_tipo: Callable[[TextoExtraido], TipoDocumento] = _detectar_tipo_real,
        obtener_parseador: Callable[[TipoDocumento], ParseadorDocumento] = _obtener_parseador_real,
        resolver_claves: Callable[..., ClavesPaciente] = _resolver_claves_real,
        vincular_episodios: Callable[[list[DocumentoParaVincular], bytes], dict[str, str]] = (
            _vincular_episodios_real
        ),
        construir_registro: Callable[..., RegistroAnonimizado] = _construir_registro_real,
        clasificar_pii: Callable[[DocumentoParseado, MotorPii], object] = _clasificar_real,
    ) -> None:
        self._resolutor = resolutor
        self._motor = motor
        self._pepper = pepper
        self._destino = destino
        self._cuarentena = cuarentena
        self._dormir = dormir
        self._extraer = extraer
        self._detectar_tipo = detectar_tipo
        self._obtener_parseador = obtener_parseador
        self._resolver_claves = resolver_claves
        self._vincular_episodios = vincular_episodios
        self._construir_registro = construir_registro
        self._clasificar_pii = clasificar_pii

    def procesar_lote(self, items: Sequence[ItemLote]) -> tuple[ResultadoDocumento, ...]:
        resultados: list[ResultadoDocumento] = []
        resueltos: list[_DocumentoResuelto] = []

        for item in items:
            try:
                resueltos.append(self._resolver_documento(item))
            except ErrorParseo as excepcion:
                resultados.append(self._a_fallo(item.id_documento, excepcion))

        episodios = self._vincular_episodios_resueltos(resueltos)

        for resuelto in resueltos:
            id_episodio = episodios[resuelto.id_documento]
            try:
                resultados.append(self._emitir(resuelto, id_episodio))
            except ErrorParseo as excepcion:
                resultados.append(self._a_fallo(resuelto.id_documento, excepcion))

        return tuple(resultados)

    # --- por documento, aislado -------------------------------------------------

    def _resolver_documento(self, item: ItemLote) -> _DocumentoResuelto:
        texto = _ejecutar_con_reintentos(
            lambda: self._extraer(item.artefacto), etapa=Etapa.EXTRACCION.value, dormir=self._dormir
        )
        tipo = self._detectar_tipo(texto)  # pura, nunca lanza (Fase 3): TIPO_NO_RECONOCIDO en vez de excepción
        parseador = self._obtener_parseador(tipo)  # ErrorParseo(TIPO_NO_RECONOCIDO) determinístico si no hay match
        documento = _ejecutar_con_reintentos(
            lambda: parseador.parsear(texto), etapa=Etapa.PARSEO.value, dormir=self._dormir
        )
        # Detección de PII sobre texto libre (design.md, "corre también sobre texto
        # libre"): se ejecuta acá para que la etapa exista explícitamente en el
        # pipeline real. El uso de sus hallazgos para depurar `secciones_texto`
        # antes de `construir_registro` es un gap conocido, no resuelto por
        # tasks.md 8.x/9.x -- ver nota en el docstring del módulo y el reporte final.
        self._clasificar_pii(documento, self._motor)
        claves = _ejecutar_con_reintentos(
            lambda: self._resolver_claves(
                documento.identidad,
                self._pepper,
                self._resolutor,
                id_documento=item.id_documento,
                etapa=Etapa.PSEUDONIMIZACION.value,
            ),
            etapa=Etapa.PSEUDONIMIZACION.value,
            dormir=self._dormir,
        )
        return _DocumentoResuelto(id_documento=item.id_documento, documento=documento, claves=claves)

    def _vincular_episodios_resueltos(self, resueltos: list[_DocumentoResuelto]) -> dict[str, str]:
        if not resueltos:
            return {}
        documentos = [
            DocumentoParaVincular(
                id_documento=r.id_documento,
                id_paciente=r.claves.id_paciente,
                fecha_estudio=r.documento.fecha_estudio,
                tipo_documento=r.documento.tipo_documento.value,
            )
            for r in resueltos
        ]
        return self._vincular_episodios(documentos, self._pepper)

    def _emitir(self, resuelto: _DocumentoResuelto, id_episodio: str) -> ExitoDocumento:
        registro = self._construir_registro(
            resuelto.documento, resuelto.claves, id_episodio=id_episodio, pepper=self._pepper
        )
        _ejecutar_con_reintentos(
            lambda: self._destino.escribir_registro(registro), etapa=Etapa.SALIDA.value, dormir=self._dormir
        )
        return ExitoDocumento(
            id_documento=resuelto.id_documento,
            tipo_documento=resuelto.documento.tipo_documento,
            id_paciente=resuelto.claves.id_paciente,
            id_episodio=id_episodio,
            timestamp=_ahora(),
        )

    def _a_fallo(self, id_documento: str, excepcion: ErrorParseo) -> FalloDocumento:
        error = ErrorDocumento(id_documento=id_documento, etapa=excepcion.etapa, codigo=excepcion.codigo)
        try:
            self._cuarentena.registrar(error)
        except Exception:
            # el registro de cuarentena en sí falló (infraestructura); el
            # ErrorDocumento igual se devuelve en el resultado del lote para
            # que este documento no se pierda en silencio, aunque no haya
            # quedado persistido en la tabla de cuarentena.
            pass
        return FalloDocumento(id_documento=id_documento, error=error, timestamp=_ahora())
