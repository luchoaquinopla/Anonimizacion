"""Ejecutor del pipeline: orquesta las etapas end-to-end, aislando el fallo por documento.
`ErrorParseo` nunca se reintenta (va directo a cuarentena); cualquier otra excepción se
considera transitoria y se reintenta con backoff, sin propagar nunca el mensaje crudo."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Protocol, cast

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.deteccion.detector_tipo import detectar_tipo as _detectar_tipo_real
from anonimizacion.extraccion.registro_trazos import capturador_de as _capturador_de_real
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido, extraer_texto_de_flujo
from anonimizacion.extraccion.trazos_pymupdf import CapturadorDePagina
from anonimizacion.ingesta.artefacto import ArtefactoCrudo
from anonimizacion.ingesta.fuente import FuenteDeArtefactos
from anonimizacion.observabilidad.bitacora_segura import BitacoraSegura
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

# 3 reintentos tras el intento inicial -- 4 intentos totales como máximo por documento/etapa.
BACKOFF_SEGUNDOS: tuple[int, ...] = (5, 30, 180)
MAX_REINTENTOS = len(BACKOFF_SEGUNDOS)
# El grupo ES la unidad completa: no hay lote posterior que traiga el estudio faltante, así que
# `False` dejaría episodios_pendientes sin contabilidad; no se expone como parámetro público.
_GRUPO_ES_UNIDAD_COMPLETA = True
_CODIGO_CUARENTENA_POR_MOTIVO = {
    MotivoCuarentenaEpisodio.ASOCIACION_AMBIGUA: CodigoErrorDocumento.EPISODIO_AMBIGUO,
    MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES: CodigoErrorDocumento.EPISODIO_INCOMPLETO,
}


class DestinoEscritura(Protocol):
    """Lo único que el ejecutor necesita de un destino. `escribir_episodio` MUST llamarse antes
    de `escribir_registro` para ese episodio: es padre por FK, violarlo rompe la escritura."""

    def escribir_registro(self, registro: RegistroAnonimizado) -> None: ...
    def escribir_episodio(self, *, id_episodio: str, id_paciente: str, fecha_ancla: date) -> None: ...


class DestinoCuarentena(Protocol):
    """`salida/cuarentena.py::EscritorCuarentena` implementa esto (Fase 7)."""

    def registrar(self, error: ErrorDocumento) -> None: ...


@dataclass(frozen=True)
class ItemLote:
    """Un documento a procesar: `id_documento` es externo al `ArtefactoCrudo`, asignado en la
    ingesta -- viaja separado, no se deriva del artefacto acá."""

    id_documento: str
    artefacto: ArtefactoCrudo


@dataclass(frozen=True)
class _DocumentoResuelto:
    """Documento que ya pasó extracción, parseo y resolución de claves; falta vincular episodio
    y emitir. `clave_documento` viaja acá para que `_emitir` la propague sin releer `ItemLote`."""

    id_documento: str
    documento: DocumentoParseado
    claves: ClavesPaciente
    clave_documento: str
    # id_campo que el PDF trae y el modelo no citó; default () para no romper tests existentes.
    campos_no_extraidos: tuple[str, ...] = ()


def _observar_sin_romper(accion: Callable[[], None]) -> None:
    """Ejecuta una llamada de observabilidad sin dejar que tumbe el pipeline: es accesoria,
    una `BitacoraSegura` rota no puede perder un documento ni un grupo."""
    try:
        accion()
    except Exception:
        pass


def _ejecutar_con_reintentos(
    funcion: Callable[[], object],
    *,
    etapa: str,
    dormir: Callable[[float], None],
) -> object:
    """Ejecuta `funcion`, reintentando solo si lanza algo que NO sea `ErrorParseo`. Al agotar
    reintentos, la excepción original se descarta y nunca se propaga su mensaje crudo."""
    intento = 0
    while True:
        try:
            resultado = funcion()
        except ErrorParseo:
            raise  # determinístico -- nunca se reintenta
        except Exception:
            if intento >= MAX_REINTENTOS:
                raise ErrorParseo(CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO, etapa=etapa) from None
            dormir(BACKOFF_SEGUNDOS[intento])
            intento += 1
            continue
        return resultado


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class EjecutorPipeline:
    """Orquesta el pipeline completo sobre un lote, aislando el fallo por documento. `resolutor`
    acepta `ResolutorClaves` (memoria) o `ResolutorClavesPostgres` (puente persistente entre
    corridas, ver `sdd/pdf-pii-anonymization/apply-progress`); `fuente` es el puerto de ingesta."""

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
        # Sólo el ECG tiene capturador registrado; laboratorio/eco devuelven None sin captura de trazos.
        capturador_de: Callable[[TipoDocumento], CapturadorDePagina | None] = _capturador_de_real,
        obtener_parseador: Callable[[TipoDocumento], ParseadorDocumento] = _obtener_parseador_real,
        obtener_reconciliador: Callable[[TipoDocumento], ReconciliadorDocumento] = _obtener_reconciliador_real,
        resolver_claves: Callable[..., ClavesPaciente] = _resolver_claves_real,
        vincular_episodios: Callable[[list[DocumentoParaVincular], bytes], ResultadoVinculacion] = (
            _vincular_episodios_real
        ),
        # None desactiva la validación de completitud de episodio: "un lote no es necesariamente
        # un episodio" es una verdad del núcleo; que en producción sí lo sea es política de despliegue.
        coordinar_episodios: Callable[..., ResultadoCoordinacion] | None = None,
        construir_registro: Callable[..., RegistroAnonimizado] = _construir_registro_real,
        clasificar_pii: Callable[[DocumentoParseado, MotorPii], object] = _clasificar_real,
        # None = sin observabilidad (accesoria por construcción, ver _observar_sin_romper).
        bitacora: BitacoraSegura | None = None,
    ) -> None:
        self._resolutor = resolutor
        self._motor = motor
        self._pepper = pepper
        self._destino = destino
        self._cuarentena = cuarentena
        self._fuente = fuente
        self._dormir = dormir
        self._bitacora = bitacora
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
        self._capturador_de = capturador_de
        self._obtener_parseador = obtener_parseador
        self._obtener_reconciliador = obtener_reconciliador
        self._resolver_claves = resolver_claves
        self._vincular_episodios = vincular_episodios
        self._coordinar_episodios = coordinar_episodios
        self._construir_registro = construir_registro
        self._clasificar_pii = clasificar_pii

    def _extraer_por_defecto(self, artefacto: ArtefactoCrudo) -> TextoExtraido:
        """`extraer` por defecto: abre vía `self._fuente` y extrae el texto del flujo, cerrado
        con `with`. `capturador_para` evita que `extraccion/` importe `deteccion` (rompe el ciclo)."""
        assert self._fuente is not None  # invariante garantizado por __init__

        def _capturador_para(texto: TextoExtraido) -> CapturadorDePagina | None:
            return self._capturador_de(self._detectar_tipo(texto))

        with self._fuente.abrir(artefacto) as flujo:
            return extraer_texto_de_flujo(flujo, capturador_para=_capturador_para)

    def procesar_lote(
        self, items: Sequence[ItemLote], *, corrida_id: str | None = None
    ) -> tuple[ResultadoDocumento, ...]:
        """Procesa el lote completo, aislando el fallo por documento. `corrida_id` es dato de
        trazabilidad, nunca clave de `ItemLote`; no participa de ninguna decisión del pipeline."""
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
        # Evita el round-trip redundante a DB por cada documento que comparte episodio.
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

        # Un evento por resultado al cierre del lote, no por intento de reintento.
        if self._bitacora is not None:
            for resultado in resultados:
                _observar_sin_romper(lambda resultado=resultado: self._bitacora.registrar(resultado.resumen_trazable()))

        return tuple(resultados)

    # --- por documento, aislado -------------------------------------------------

    def _resolver_documento(self, item: ItemLote) -> _DocumentoResuelto:
        texto = _ejecutar_con_reintentos(
            lambda: self._extraer(item.artefacto),
            etapa=Etapa.EXTRACCION.value,
            dormir=self._dormir,
        )
        tipo = self._detectar_tipo(texto)  # pura, nunca lanza (Fase 3): TIPO_NO_RECONOCIDO en vez de excepción
        try:
            parseador = self._obtener_parseador(tipo)  # ErrorParseo(TIPO_NO_RECONOCIDO) determinístico si no hay match
            documento = _ejecutar_con_reintentos(
                lambda: parseador.parsear(texto),
                etapa=Etapa.PARSEO.value,
                dormir=self._dormir,
            )
            reconciliador = self._obtener_reconciliador(tipo)
            # reconciliar nunca lanza por campos sin citar: llegar acá es "sin problema de integridad", no "completo".
            campos_no_extraidos = cast(
                "tuple[str, ...]",
                _ejecutar_con_reintentos(
                    lambda: reconciliador.reconciliar(documento, texto),
                    etapa=Etapa.RECONCILIACION.value,
                    dormir=self._dormir,
                ),
            )
            # Clasifica PII en sus namespaces; la redacción efectiva de secciones_texto ocurre en _emitir, vía construir_registro.
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
                campos_no_extraidos=campos_no_extraidos,
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
        # Todo resuelto cae en aprobado o cuarentena; fallar acá es preferible a que se evapore del embudo en silencio.
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
        """Escribe el episodio (si todavía no se escribió en este lote, FK de las filas hijas)
        y luego el registro. Si la escritura del episodio agota reintentos, no se marca como
        escrito: el próximo documento del mismo episodio la reintenta."""
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
                campos_no_extraidos=resuelto.campos_no_extraidos,
            ),
            corrida_id=corrida_id,
        )
        _ejecutar_con_reintentos(
            lambda: self._destino.escribir_registro(registro),
            etapa=Etapa.SALIDA.value,
            dormir=self._dormir,
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
            detalle_parseo=excepcion.detalle_parseo,
        )
        try:
            self._cuarentena.registrar(error)
        except Exception:
            # Falló el registro de cuarentena (infra); igual se devuelve el ErrorDocumento para no perder el documento en silencio.
            pass
        return FalloDocumento(id_documento=id_documento, error=error, timestamp=_ahora())
