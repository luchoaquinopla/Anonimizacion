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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from anonimizacion.dominio.estados_corrida import EstadoDocumentoCorrida
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.ingesta.fuente import FuenteLocal, HuellasEnMemoria, RegistroDeHuellas
from anonimizacion.observabilidad.bitacora_segura import BitacoraSegura
from anonimizacion.observabilidad.metricas import ColectorMetricas, MetricasEnMemoria
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.coordinador_episodios import coordinar_episodios
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
    # Puntos de inyeccion de la raiz de composicion, no parches de test:
    # `None` significa "usar el valor de produccion". Existen para que el banco
    # de carga pueda pasar por ESTA fabrica en vez de duplicarla -- si el banco
    # arma el ejecutor a mano, cualquier cableado nuevo que se agregue aca deja
    # de llegarle en silencio, que es exactamente lo que ya paso con la
    # validacion de episodio (ver `tests/carga/test_cableado_del_banco.py`).
    dormir: Callable[[float], None] | None = None,
    resolver_claves: Callable[..., object] | None = None,
    # `metricas`/`bitacora` (design.md, Decisión 7): misma semántica que
    # `dormir`/`resolver_claves` de acá arriba -- `None` significa "usar el
    # valor de producción" (`MetricasEnMemoria()`/`BitacoraSegura()`), nunca
    # "desactivar la observabilidad". El punto de inyección existe para que
    # los tests puedan espiar sin duplicar esta fábrica -- ver
    # `tests/pipeline/test_observabilidad_cableada.py`.
    metricas: ColectorMetricas | None = None,
    bitacora: BitacoraSegura | None = None,
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
            **({"dormir": dormir} if dormir is not None else {}),
            **({"resolver_claves": resolver_claves} if resolver_claves is not None else {}),
            # La validacion de completitud de episodio vive ACA, no en el default
            # del ejecutor: "un lote no es necesariamente un episodio" es una verdad
            # del nucleo, "en produccion el lote ES un grupo de paciente" es politica
            # de despliegue. Sin esta inyeccion, un grupo al que le falta un estudio
            # se publica sin aviso -- ver
            # `tests/pipeline/test_modo_sin_validacion_de_episodio.py`.
            coordinar_episodios=coordinar_episodios,
            # `None` = produccion (design.md, Decision 7): a diferencia de
            # `dormir`/`resolver_claves`, acá SIEMPRE se pasa una instancia --
            # el default de `EjecutorPipeline` es "sin observabilidad", y esa
            # semántica es correcta para sus tests unitarios pero NO para esta
            # raíz de composición real.
            metricas=metricas if metricas is not None else MetricasEnMemoria(),
            # `motor_pii=motor` (revisión fresca post-Tramo 3): sin esto, la
            # capa 2 de redacción de `BitacoraSegura` queda en modo degradado
            # (solo regex de DNI, ver docstring de `bitacora_segura.py`). El
            # `motor` ya está cargado y es el MISMO que usa el resto del
            # pipeline (`EjecutorPipeline._emitir` lo inyecta en
            # `construir_registro`/`redactar_texto` -- ver `pii/redaccion.py`):
            # compartirlo acá no agrega estado nuevo, `MotorPii.detectar` no
            # acumula nada entre llamadas.
            bitacora=bitacora if bitacora is not None else BitacoraSegura(motor_pii=motor),
        )

    return _fabrica


@app.task(name="anonimizacion.procesar_grupo")
def procesar_grupo(corrida_id: str, referencias: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    """Procesa como un solo lote los documentos de un grupo (un paciente, un episodio).

    La unidad de trabajo es el grupo y no el documento porque la validacion de
    episodio necesita ver juntos todos los estudios del paciente: un lote de un
    solo documento nunca contiene los tres tipos requeridos y terminaria mandando
    el 100 % a cuarentena.

    El mensaje transporta SOLO referencias -- `{id_documento, uri, sha256}` por
    documento, nunca contenido ni PII. Se transporta la lista y no la ruta del
    directorio a proposito: si el trabajador enumerara la carpeta, el `sha256` se
    calcularia ahi y la identidad del trabajo dejaria de estar en el mensaje, de
    modo que un reintento sobre una carpeta que cambio procesaria otro grupo.

    `corrida_id` (spec `trazabilidad-por-corrida`, design.md Decision 1) viaja
    como parametro HERMANO del lote, nunca como una cuarta clave de la
    referencia por documento -- eso relajaria el centinela de claves exactas
    de mas abajo. Es un UUID administrativo asignado por quien lanza la corrida,
    no PII: no se deriva de contenido ni de ruta de ningun documento.
    """
    items = [
        ItemLote(
            id_documento=referencia["id_documento"],
            artefacto=ArtefactoCrudo(
                uri=referencia["uri"],
                sha256=referencia["sha256"],
                formato=FormatoArtefacto.PDF,
            ),
        )
        for referencia in referencias
    ]
    if not items:
        raise ValueError("un grupo requiere al menos un documento")

    ejecutor = _obtener_ejecutor()
    return [
        resultado.resumen_trazable() for resultado in ejecutor.procesar_lote(items, corrida_id=corrida_id)
    ]

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
