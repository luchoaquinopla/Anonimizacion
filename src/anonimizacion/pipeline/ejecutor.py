"""Ejecutor del pipeline: orquesta las etapas end-to-end, aislando el fallo por documento.

Spec `batch-processing`: (1) "Aislamiento de fallos por documento" -- el
fallo de un documento nunca detiene el procesamiento del resto del lote;
(2) "Reintentos ante fallos transitorios" -- solo errores NO tipados
(IO/conexión, nunca `ErrorParseo`) se reintentan, con backoff; (3)
"Trazabilidad sin PII" -- ver `pipeline/resultado.py`, que ya construye por
diseño resúmenes sin PII.

Secuencia por documento (design.md, "Data Flow"):
`extraer -> detectar_tipo -> obtener_parseador+parsear -> reconciliar ->
[detección de PII sobre texto libre] -> resolver_claves -> [batch:
coordinar_episodios] -> construir_registro -> escribir`. La coordinación es
la única etapa que opera sobre TODO el lote a la vez: espera a que cada
documento esté reconciliado y bloquea la anonimización/salida de episodios
incompletos o ambiguos. Sin el coordinador durable inyectado se conserva el
vínculo histórico para los lotes existentes.

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
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Protocol

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.deteccion.detector_tipo import detectar_tipo as _detectar_tipo_real
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido, extraer_texto_de_flujo
from anonimizacion.ingesta.artefacto import ArtefactoCrudo
from anonimizacion.ingesta.fuente import FuenteDeArtefactos
from anonimizacion.parseo.base import ParseadorDocumento
from anonimizacion.parseo.registro import obtener_parseador as _obtener_parseador_real
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pii.politica import clasificar as _clasificar_real
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesProtocol
from anonimizacion.pseudonimizacion.resolutor_claves import resolver_claves as _resolver_claves_real
from anonimizacion.pseudonimizacion.vinculacion import DocumentoParaVincular, MetadataEpisodio, ResultadoVinculacion
from anonimizacion.pseudonimizacion.vinculacion import vincular_episodios as _vincular_episodios_real
from anonimizacion.salida.constructor_registro import construir_registro as _construir_registro_real
from anonimizacion.reconciliacion.base import ReconciliadorDocumento
from anonimizacion.reconciliacion.registro import obtener_reconciliador as _obtener_reconciliador_real

from .coordinador_episodios import (
    DocumentoParaCoordinar,
    MotivoCuarentenaEpisodio,
    ResultadoCoordinacion,
)
from .etapas import Etapa
from .resultado import ExitoDocumento, FalloDocumento, ResultadoDocumento

# Backoff exponencial fijo (design.md, tasks.md 9.1): 3 reintentos tras el
# intento inicial -- 4 intentos totales como máximo por documento/etapa.
# `trabajadores/politica_reintentos.py` reusa estas mismas constantes (no se
# duplica el número en dos lugares).
BACKOFF_SEGUNDOS: tuple[int, ...] = (5, 30, 180)
MAX_REINTENTOS = len(BACKOFF_SEGUNDOS)
# El grupo ES la unidad completa de trabajo (design.md, Decisión 6): no hay un
# lote posterior de esta misma corrida que pueda traer el estudio faltante,
# así que no hay nada que dejar pendiente. Con `False` la coordinación
# devolvería `episodios_pendientes` que `_coordinar_resueltos` no sabe
# contabilizar -- ver el centinela en `tests/pipeline/test_particion_total_del_lote.py`.
# No se expone como parámetro público: ofrecer la perilla sin la contabilidad
# detrás sería ofrecer la trampa con un nombre bonito.
_GRUPO_ES_UNIDAD_COMPLETA = True
_CODIGO_CUARENTENA_POR_MOTIVO = {
    MotivoCuarentenaEpisodio.ASOCIACION_AMBIGUA: CodigoErrorDocumento.EPISODIO_AMBIGUO,
    MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES: CodigoErrorDocumento.EPISODIO_INCOMPLETO,
}


class DestinoEscritura(Protocol):
    """Lo único que el ejecutor necesita de un destino (`salida/destinos/postgres.py` lo implementa).

    `escribir_episodio` (fix post-PR9): la fila `episodio` es padre por FK de
    `resultado_laboratorio`/`medicion_ecg`/`medicion_eco`/`texto_seccion_eco`
    (ver `salida/modelos_orm.py`) -- el ejecutor debe escribirla ANTES de
    llamar `escribir_registro` para cualquier documento de ese episodio, o
    la escritura del registro viola la FK (`ForeignKeyViolation` en Postgres
    real). Ver docstring de `_emitir` para el detalle del fix.
    """

    def escribir_registro(self, registro: RegistroAnonimizado) -> None: ...
    def escribir_episodio(self, *, id_episodio: str, id_paciente: str, fecha_ancla: date) -> None: ...


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
    """Documento que ya pasó extracción, parseo y resolución de claves; falta vincular episodio + emitir.

    `clave_documento` (spec `escritura-idempotente`): identidad estable del
    documento, derivada en `_resolver_documento` a partir de
    `item.artefacto.sha256` -- ya viaja acá para que `_emitir` la propague a
    `construir_registro` sin tener que volver a tocar el `ItemLote` original.
    """

    id_documento: str
    documento: DocumentoParseado
    claves: ClavesPaciente
    clave_documento: str


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
    """Orquesta el pipeline completo sobre un lote, aislando el fallo por documento.

    `resolutor` (fix post-merge, ver `sdd/pdf-pii-anonymization/apply-progress`,
    sección "Fix: persistencia del puente id_alt_paciente en Postgres entre
    corridas"): tipado contra `ResolutorClavesProtocol`, no contra la clase
    concreta `ResolutorClaves` -- acepta indistintamente un `ResolutorClaves`
    en memoria (uso en tests, o un lote único procesado de punta a punta en
    la misma corrida) o un `ResolutorClavesPostgres` (uso real en producción,
    ver `scripts/procesar_carpeta.py`: el puente sobrevive entre corridas
    separadas del programa porque vive en la tabla `vinculo_paciente`, no en
    memoria).

    `fuente` (openspec `puerto-de-ingesta`, design.md): puerto de ingesta
    (`ingesta/fuente.py::FuenteDeArtefactos`) usado para construir el
    `extraer` por defecto -- `extraer_texto_de_flujo(fuente.abrir(artefacto))`.
    El core ya no conoce `pathlib`: ningún `Path(artefacto.uri)` vive en este
    módulo. `fuente` es opcional solo porque los tests inyectan su propio
    `extraer` fake (no necesitan abrir nada real); en producción,
    `trabajadores/tareas.py::configurar_ejecutor` siempre construye una
    `FuenteLocal` y la inyecta acá.
    """

    def __init__(
        self,
        *,
        resolutor: ResolutorClavesProtocol,
        motor: MotorPii,
        pepper: bytes,
        destino: DestinoEscritura,
        cuarentena: DestinoCuarentena,
        fuente: FuenteDeArtefactos | None = None,
        dormir: Callable[[float], None] = time.sleep,
        extraer: Callable[[ArtefactoCrudo], TextoExtraido] | None = None,
        detectar_tipo: Callable[[TextoExtraido], TipoDocumento] = _detectar_tipo_real,
        obtener_parseador: Callable[[TipoDocumento], ParseadorDocumento] = _obtener_parseador_real,
        obtener_reconciliador: Callable[[TipoDocumento], ReconciliadorDocumento] = _obtener_reconciliador_real,
        resolver_claves: Callable[..., ClavesPaciente] = _resolver_claves_real,
        vincular_episodios: Callable[[list[DocumentoParaVincular], bytes], ResultadoVinculacion] = (
            _vincular_episodios_real
        ),
        # `None` DESACTIVA la validacion de completitud de episodio: sin
        # coordinador, `_coordinar_resueltos` no aparta ningun documento.
        #
        # El default se conserva en `None` a proposito: "un lote no es
        # necesariamente un episodio" es una verdad del nucleo. Que en produccion
        # el lote SEA el grupo de un paciente es politica de despliegue, y por eso
        # el coordinador lo inyecta la raiz de composicion
        # (`trabajadores/tareas.py::construir_fabrica_ejecutor`), no este default.
        # Ver `tests/pipeline/test_modo_sin_validacion_de_episodio.py`, que fija
        # las dos mitades de esa afirmacion.
        coordinar_episodios: Callable[..., ResultadoCoordinacion] | None = None,
        construir_registro: Callable[..., RegistroAnonimizado] = _construir_registro_real,
        clasificar_pii: Callable[[DocumentoParseado, MotorPii], object] = _clasificar_real,
    ) -> None:
        self._resolutor = resolutor
        self._motor = motor
        self._pepper = pepper
        self._destino = destino
        self._cuarentena = cuarentena
        self._fuente = fuente
        self._dormir = dormir
        if extraer is not None:
            self._extraer = extraer
        elif fuente is not None:
            self._extraer = self._extraer_por_defecto
        else:
            raise ValueError(
                "EjecutorPipeline requiere `fuente` (o un `extraer` explicito para "
                "tests): sin una fuente no hay forma de abrir el artefacto para "
                "extraer su texto."
            )
        self._detectar_tipo = detectar_tipo
        self._obtener_parseador = obtener_parseador
        self._obtener_reconciliador = obtener_reconciliador
        self._resolver_claves = resolver_claves
        self._vincular_episodios = vincular_episodios
        self._coordinar_episodios = coordinar_episodios
        self._construir_registro = construir_registro
        self._clasificar_pii = clasificar_pii

    def _extraer_por_defecto(self, artefacto: ArtefactoCrudo) -> TextoExtraido:
        """`extraer` por defecto: abre el artefacto vía `self._fuente` y
        extrae su texto del flujo, sin tocar `pathlib` (design.md, Decisión 2
        y 4). `self._fuente` no puede ser `None` acá -- `__init__` ya validó
        que si `extraer` no se proveyó, `fuente` sí.

        Ciclo de vida: `fuente.abrir()` entrega un `BinaryIO` fresco; este es
        el LLAMADOR, así que lo cierra con `with` apenas termina de leerlo.
        """
        assert self._fuente is not None  # invariante garantizado por __init__
        with self._fuente.abrir(artefacto) as flujo:
            return extraer_texto_de_flujo(flujo)

    def procesar_lote(
        self, items: Sequence[ItemLote], *, corrida_id: str | None = None
    ) -> tuple[ResultadoDocumento, ...]:
        """Procesa el lote completo, aislando el fallo por documento.

        `corrida_id` (spec `trazabilidad-por-corrida`, design.md Decisión 1):
        parámetro HERMANO del lote, nunca una cuarta clave de `ItemLote` ni de
        la referencia de cola -- eso rompería el centinela de claves exactas
        de `trabajadores/tareas.py::procesar_grupo`. Se copia tal cual a
        `RegistroAnonimizado.corrida_id` (`_emitir`) y a
        `ErrorDocumento.corrida_id` (`_a_fallo`), y no participa de ninguna
        decisión del pipeline: es un dato de trazabilidad, no de negocio.
        """
        resultados: list[ResultadoDocumento] = []
        resueltos: list[_DocumentoResuelto] = []

        for item in items:
            try:
                resueltos.append(self._resolver_documento(item))
            except ErrorParseo as excepcion:
                resultados.append(
                    self._a_fallo(
                        item.id_documento,
                        excepcion,
                        getattr(excepcion, "tipo_documento", None),
                        corrida_id=corrida_id,
                    )
                )

        resueltos, resultado_vinculacion, fallos_coordinacion = self._coordinar_resueltos(
            resueltos, corrida_id=corrida_id
        )
        resultados.extend(fallos_coordinacion)
        # episodios ya escritos EN ESTE LOTE (fix post-PR9): `escribir_episodio`
        # es idempotente del lado del destino (ver `EscritorPostgres.
        # escribir_episodio`), pero este set evita el round-trip redundante a
        # DB para cada documento adicional que comparte episodio, y mantiene
        # la semántica "una escritura por episodio único" que pide el fix.
        episodios_escritos: set[str] = set()

        for resuelto in resueltos:
            id_episodio = resultado_vinculacion.id_episodio_por_documento[resuelto.id_documento]
            try:
                resultados.append(
                    self._emitir(resuelto, id_episodio, resultado_vinculacion, episodios_escritos, corrida_id=corrida_id)
                )
            except ErrorParseo as excepcion:
                resultados.append(
                    self._a_fallo(
                        resuelto.id_documento, excepcion, resuelto.documento.tipo_documento, corrida_id=corrida_id
                    )
                )

        return tuple(resultados)

    # --- por documento, aislado -------------------------------------------------

    def _resolver_documento(self, item: ItemLote) -> _DocumentoResuelto:
        texto = _ejecutar_con_reintentos(
            lambda: self._extraer(item.artefacto), etapa=Etapa.EXTRACCION.value, dormir=self._dormir
        )
        tipo = self._detectar_tipo(texto)  # pura, nunca lanza (Fase 3): TIPO_NO_RECONOCIDO en vez de excepción
        try:
            parseador = self._obtener_parseador(tipo)  # ErrorParseo(TIPO_NO_RECONOCIDO) determinístico si no hay match
            documento = _ejecutar_con_reintentos(
                lambda: parseador.parsear(texto), etapa=Etapa.PARSEO.value, dormir=self._dormir
            )
            reconciliador = self._obtener_reconciliador(tipo)
            _ejecutar_con_reintentos(
                lambda: reconciliador.reconciliar(documento, texto),
                etapa=Etapa.RECONCILIACION.value,
                dormir=self._dormir,
            )
            # Detección de PII sobre texto libre (design.md, "corre también sobre texto
        # libre"): se ejecuta acá para que la etapa exista explícitamente en el
        # pipeline real y clasifique la PII en sus namespaces (paciente/médico/
        # cuasi-identificador, ver `pii/politica.py`). La REDACCIÓN efectiva de
        # `secciones_texto` (el gap dejado abierto por PR7/PR8) se aplica más
        # abajo, en `_emitir`, pasando `self._motor` a `construir_registro` --
        # ver `pii/redaccion.py` y el docstring de `salida/constructor_registro.py`.
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
            clave_documento = generar_clave_documento(self._pepper, item.artefacto.sha256)
            return _DocumentoResuelto(
                id_documento=item.id_documento,
                documento=documento,
                claves=claves,
                clave_documento=clave_documento,
            )
        except ErrorParseo as error:
            error.tipo_documento = tipo
            raise

    def _vincular_episodios_resueltos(self, resueltos: list[_DocumentoResuelto]) -> ResultadoVinculacion:
        if not resueltos:
            return ResultadoVinculacion(id_episodio_por_documento={}, metadata_por_episodio={})
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

    def _coordinar_resueltos(
        self, resueltos: list[_DocumentoResuelto], *, corrida_id: str | None = None
    ) -> tuple[list[_DocumentoResuelto], ResultadoVinculacion, list[FalloDocumento]]:
        if self._coordinar_episodios is None:
            return resueltos, self._vincular_episodios_resueltos(resueltos), []

        documentos = [
            DocumentoParaCoordinar(
                id_documento=resuelto.id_documento,
                id_paciente=resuelto.claves.id_paciente,
                tipo_documento=resuelto.documento.tipo_documento,
                fecha_estudio=resuelto.documento.fecha_estudio,
            )
            for resuelto in resueltos
        ]
        coordinacion = self._coordinar_episodios(
            documentos, pepper=self._pepper, corrida_cerrada=_GRUPO_ES_UNIDAD_COMPLETA
        )
        resultado_vinculacion = self._resultado_vinculacion_desde_coordinacion(coordinacion)
        resueltos_aprobados = [
            resuelto
            for resuelto in resueltos
            if resuelto.id_documento in resultado_vinculacion.id_episodio_por_documento
        ]
        fallos = [
            self._a_fallo(
                resuelto.id_documento,
                ErrorParseo(
                    self._codigo_por_motivo(motivo),
                    etapa=Etapa.COORDINACION.value,
                ),
                resuelto.documento.tipo_documento,
                corrida_id=corrida_id,
            )
            for resuelto in resueltos
            if (motivo := coordinacion.documentos_en_cuarentena.get(resuelto.id_documento)) is not None
        ]
        # Invariante de la Decisión 6: todo resuelto cae exactamente en una de
        # las dos puertas (aprobado o cuarentena). Un `episodios_pendientes`
        # no vacío -- imposible hoy con `_GRUPO_ES_UNIDAD_COMPLETA` fijo, pero
        # alcanzable si alguien inyecta un coordinador distinto -- dejaría
        # documentos sin contabilizar en ninguna de las dos listas: fallar acá
        # es preferible a que ese documento se evapore del embudo en silencio.
        contabilizados = {resuelto.id_documento for resuelto in resueltos_aprobados}
        contabilizados.update(fallo.id_documento for fallo in fallos)
        sin_contabilizar = {resuelto.id_documento for resuelto in resueltos} - contabilizados
        if sin_contabilizar:
            raise RuntimeError(
                f"_coordinar_resueltos dejo {len(sin_contabilizar)} documento(s) sin contabilizar "
                "(ni aprobados ni en cuarentena) -- _GRUPO_ES_UNIDAD_COMPLETA asume que la "
                "coordinacion nunca deja episodios_pendientes; si el coordinador inyectado los "
                "produjo de todos modos, no hay contabilidad para ellos en este pipeline"
            )
        return resueltos_aprobados, resultado_vinculacion, fallos

    @staticmethod
    def _resultado_vinculacion_desde_coordinacion(coordinacion: ResultadoCoordinacion) -> ResultadoVinculacion:
        id_episodio_por_documento = {
            documento.id_documento: episodio.id_episodio
            for episodio in coordinacion.episodios_aprobados
            for documento in episodio.documentos
        }
        metadata_por_episodio = {
            episodio.id_episodio: MetadataEpisodio(
                id_paciente=episodio.id_paciente,
                fecha_ancla=episodio.fecha_ancla,
            )
            for episodio in coordinacion.episodios_aprobados
        }
        return ResultadoVinculacion(id_episodio_por_documento, metadata_por_episodio)

    @staticmethod
    def _codigo_por_motivo(motivo: MotivoCuarentenaEpisodio) -> CodigoErrorDocumento:
        return _CODIGO_CUARENTENA_POR_MOTIVO[motivo]

    def _emitir(
        self,
        resuelto: _DocumentoResuelto,
        id_episodio: str,
        resultado_vinculacion: ResultadoVinculacion,
        episodios_escritos: set[str],
        *,
        corrida_id: str | None = None,
    ) -> ExitoDocumento:
        """Escribe el episodio (si todavía no se escribió en este lote) y luego el registro.

        Fix post-PR9: `resultado_laboratorio`/`medicion_ecg`/`medicion_eco`/
        `texto_seccion_eco` son FK contra `episodio.id_episodio` (ver
        `salida/modelos_orm.py`) -- escribir el registro sin que exista antes
        la fila `episodio` viola esa FK (`ForeignKeyViolation` en Postgres
        real). `escribir_episodio` se llama ANTES de `escribir_registro`,
        envuelta en la misma política de reintentos, y solo una vez por
        `id_episodio` (idempotente del lado del destino de todos modos, ver
        `EscritorPostgres.escribir_episodio`). Si la escritura del episodio
        falla de forma transitoria y agota reintentos, `episodios_escritos`
        NO se marca -- el próximo documento del mismo episodio la reintenta,
        preservando el aislamiento de fallo por documento (spec
        `batch-processing`).
        """
        if id_episodio not in episodios_escritos:
            metadata = resultado_vinculacion.metadata_por_episodio[id_episodio]
            _ejecutar_con_reintentos(
                lambda: self._destino.escribir_episodio(
                    id_episodio=id_episodio, id_paciente=metadata.id_paciente, fecha_ancla=metadata.fecha_ancla
                ),
                etapa=Etapa.SALIDA.value,
                dormir=self._dormir,
            )
            episodios_escritos.add(id_episodio)

        registro = replace(
            self._construir_registro(
                resuelto.documento,
                resuelto.claves,
                id_episodio=id_episodio,
                pepper=self._pepper,
                clave_documento=resuelto.clave_documento,
                motor_pii=self._motor,
            ),
            corrida_id=corrida_id,
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

    def _a_fallo(
        self,
        id_documento: str,
        excepcion: ErrorParseo,
        tipo_documento: TipoDocumento | None = None,
        *,
        corrida_id: str | None = None,
    ) -> FalloDocumento:
        error = ErrorDocumento(
            id_documento=id_documento,
            etapa=excepcion.etapa,
            codigo=excepcion.codigo,
            campo=excepcion.campo,
            pagina=excepcion.pagina,
            tipo_documento=tipo_documento,
            corrida_id=corrida_id,
        )
        try:
            self._cuarentena.registrar(error)
        except Exception:
            # el registro de cuarentena en sí falló (infraestructura); el
            # ErrorDocumento igual se devuelve en el resultado del lote para
            # que este documento no se pierda en silencio, aunque no haya
            # quedado persistido en la tabla de cuarentena.
            pass
        return FalloDocumento(id_documento=id_documento, error=error, timestamp=_ahora())
