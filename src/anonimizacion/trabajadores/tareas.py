"""Tarea Celery por documento (tasks.md 9.2).

Requisito crítico (spec `batch-processing`, design.md "Sin PII en cola, logs
ni DLQ"): el mensaje de cola transporta SOLO `{id_documento, uri, sha256}` --
nunca contenido del documento, nunca PII. La firma de `procesar_documento`
ES esa restricción por construcción: no hay ningún parámetro por el que
pueda colarse un dato distinto. La tarea reconstruye un `ArtefactoCrudo` a
partir de esos 3 campos y delega el procesamiento real a
`pipeline/ejecutor.py::EjecutorPipeline`, que ya conoce el aislamiento de
fallo y la política de reintentos (Fase 8) -- esta tarea no reimplementa
nada de eso.

Construir el `EjecutorPipeline` real (pepper cargado desde el almacén
seguro, `MotorPii` con spaCy, `Engine` de Postgres) es responsabilidad de la
composición de la app en el arranque del worker, no de este módulo: acoplar
esa construcción pesada al import de `tareas.py` haría que importarlo en un
test (o en el arranque de cualquier proceso que solo necesite inspeccionar
la tarea) cargue spaCy/Presidio y abra una conexión de DB como side effect.
`configurar_ejecutor` es el punto de inyección explícito; si nadie lo llamó,
`procesar_documento` falla ruidoso con `RuntimeError` en vez de construir
dependencias por default silenciosamente.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from anonimizacion.dominio.estados_corrida import EstadoDocumentoCorrida
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.ingesta.fuente import FuenteLocal, HuellasEnMemoria, RegistroDeHuellas
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import DestinoCuarentena, DestinoEscritura, EjecutorPipeline, ItemLote
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesProtocol
from anonimizacion.trabajadores.app import aplicar_configuracion_cola, app

aplicar_configuracion_cola(os.environ)

FabricaEjecutor = Callable[[], EjecutorPipeline]

_fabrica_ejecutor: FabricaEjecutor | None = None


def configurar_ejecutor(fabrica: FabricaEjecutor) -> None:
    """Registra cómo construir el `EjecutorPipeline` real -- llamar al arrancar el worker."""
    global _fabrica_ejecutor
    _fabrica_ejecutor = fabrica


def _obtener_ejecutor() -> EjecutorPipeline:
    if _fabrica_ejecutor is None:
        raise RuntimeError(
            "EjecutorPipeline no configurado -- llamar a "
            "trabajadores.tareas.configurar_ejecutor(...) en el arranque del "
            "worker antes de procesar tareas."
        )
    return _fabrica_ejecutor()


def construir_fabrica_ejecutor(
    *,
    raices: tuple[Path, ...],
    resolutor: ResolutorClavesProtocol,
    motor: MotorPii,
    pepper: bytes,
    destino: DestinoEscritura,
    cuarentena: DestinoCuarentena,
    tope_bytes: int | None = None,
    huellas: RegistroDeHuellas | None = None,
) -> FabricaEjecutor:
    """Arma la `FabricaEjecutor` real para registrar con `configurar_ejecutor`.

    Raíz de composición del worker (openspec `puerto-de-ingesta`, design.md
    Decisión 2): la `FuenteLocal` se construye UNA sola vez acá, no en cada
    tarea -- el worker solo llama `abrir()` sobre ella (nunca `listar()` ni
    dedup: ver la decisión al inicio de tasks.md sobre por qué
    `HuellasDeCorrida` queda fuera de este cambio). `EscritorCuarentena`
    satisface tanto `DestinoCuarentena` (`pipeline/ejecutor.py`) como
    `SumideroCuarentena` (`ingesta/fuente.py`) por tipado estructural, sin
    que ninguno de los dos módulos importe al otro.

    `directorio` de `FuenteLocal` se fija a la primera raíz autorizada: esta
    fábrica nunca llama `listar()` (por eso no importa cuál), solo `abrir()`,
    que valida contra el conjunto completo de `raices`.
    """
    fuente = FuenteLocal(
        raices=raices,
        directorio=raices[0],
        huellas=huellas or HuellasEnMemoria(),
        cuarentena=cuarentena,
        **({"tope_bytes": tope_bytes} if tope_bytes is not None else {}),
    )

    def _fabrica() -> EjecutorPipeline:
        return EjecutorPipeline(
            resolutor=resolutor,
            motor=motor,
            pepper=pepper,
            destino=destino,
            cuarentena=cuarentena,
            fuente=fuente,
        )

    return _fabrica


@app.task(name="anonimizacion.procesar_documento")
def procesar_documento(id_documento: str, uri: str, sha256: str) -> dict[str, object]:
    """Procesa un documento a partir de su referencia de cola (nunca su contenido)."""
    artefacto = ArtefactoCrudo(uri=uri, sha256=sha256, formato=FormatoArtefacto.PDF)
    item = ItemLote(id_documento=id_documento, artefacto=artefacto)

    ejecutor = _obtener_ejecutor()
    (resultado,) = ejecutor.procesar_lote([item])
    return resultado.resumen_trazable()

FabricaExtractor = Callable[[], object]

_fabrica_extractor: FabricaExtractor | None = None
_repositorio_corridas: object | None = None


def configurar_extractor(fabrica: FabricaExtractor, repositorio: object) -> None:
    """Configura la extracción por etapas y su persistencia durable."""
    global _fabrica_extractor, _repositorio_corridas
    _fabrica_extractor = fabrica
    _repositorio_corridas = repositorio


@app.task(name="anonimizacion.procesar_extraccion_minima")
def procesar_extraccion_minima(corrida_id: str, uri: str, sha256: str) -> dict[str, str]:
    """Extrae lo mínimo una sola vez y conserva el estado para reanudar."""
    if _fabrica_extractor is None or _repositorio_corridas is None:
        raise RuntimeError("extractor de documentos no configurado")
    documento = next(
        documento
        for documento in _repositorio_corridas.documentos_para_reanudar(corrida_id)
        if documento.huella_contenido == sha256
    )
    if documento.estado.value == "extraido_minimo":
        return {"estado": documento.estado.value}
    if documento.estado.value != "inventariado":
        raise RuntimeError("estado no apto para extraccion minima")

    version = documento.version
    documento.avanzar_a(EstadoDocumentoCorrida.CLASIFICADO)
    if not _repositorio_corridas.actualizar_documento(documento, version_esperada=version):
        return {"estado": "en_progreso"}
    _fabrica_extractor().extraer_minimo(ArtefactoCrudo(uri=uri, sha256=sha256, formato=FormatoArtefacto.PDF))
    version = documento.version
    documento.avanzar_a(EstadoDocumentoCorrida.EXTRAIDO_MINIMO)
    _repositorio_corridas.actualizar_documento(documento, version_esperada=version)
    return {"estado": documento.estado.value}


@app.task(name="anonimizacion.procesar_extraccion_completa")
def procesar_extraccion_completa(corrida_id: str, uri: str, sha256: str) -> dict[str, str]:
    """Persiste extracción completa de un documento ya asociado, sin publicarlo."""
    if _fabrica_extractor is None or _repositorio_corridas is None:
        raise RuntimeError("extractor de documentos no configurado")
    documento = next(
        documento
        for documento in _repositorio_corridas.documentos_para_reanudar(corrida_id)
        if documento.huella_contenido == sha256
    )
    if documento.estado is EstadoDocumentoCorrida.EXTRAIDO_COMPLETO:
        return {"estado": documento.estado.value}
    if documento.estado is not EstadoDocumentoCorrida.ASOCIADO:
        raise RuntimeError("estado no apto para extraccion completa")

    _fabrica_extractor().extraer_completo(ArtefactoCrudo(uri=uri, sha256=sha256, formato=FormatoArtefacto.PDF))
    version = documento.version
    documento.avanzar_a(EstadoDocumentoCorrida.EXTRAIDO_COMPLETO)
    if not _repositorio_corridas.actualizar_documento(documento, version_esperada=version):
        return {"estado": "en_progreso"}
    return {"estado": documento.estado.value}
