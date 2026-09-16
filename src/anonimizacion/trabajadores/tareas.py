"""Procesamiento de un grupo de documentos. El mensaje transporta SOLO
`{id_documento, uri, sha256}`, nunca contenido ni PII -- la firma de la tarea es esa
restricción por construcción. Delega en `EjecutorPipeline`, que ya conoce el
aislamiento de fallo. Construir el `EjecutorPipeline` real es responsabilidad del
arranque del worker, no de este módulo: `configurar_ejecutor` es el punto de
inyección explícito; sin él, `procesar_grupo` falla ruidoso en vez de construir
dependencias pesadas (spaCy, DB) por default."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.ingesta.fuente import FuenteLocal, HuellasEnMemoria, RegistroDeHuellas
from anonimizacion.observabilidad.bitacora_segura import BitacoraSegura
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.coordinador_episodios import coordinar_episodios
from anonimizacion.pipeline.ejecutor import DestinoCuarentena, DestinoEscritura, EjecutorPipeline, ItemLote
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesProtocol

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
    # Puntos de inyección de la raíz de composición, no parches de test: `None`
    # significa "usar el valor de producción". Existen para que el banco de carga
    # pase por esta fábrica en vez de duplicarla -- ver test_cableado_del_banco.py.
    dormir: Callable[[float], None] | None = None,
    resolver_claves: Callable[..., object] | None = None,
    bitacora: BitacoraSegura | None = None,
) -> FabricaEjecutor:
    """Arma la `FabricaEjecutor` real para registrar con `configurar_ejecutor`. La
    `FuenteLocal` se construye una sola vez acá; `directorio` se fija a la primera
    raíz porque esta fábrica nunca llama `listar()`, sólo `abrir()`."""
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
            # Vive acá, no en el default del ejecutor: "un lote no es necesariamente
            # un episodio" es verdad del núcleo, "el lote ES un grupo" es política.
            coordinar_episodios=coordinar_episodios,
            # Sin motor_pii=motor, la capa 2 de BitacoraSegura queda en modo degradado
            # (sólo regex DNI). Reusa el mismo motor del resto del pipeline.
            bitacora=bitacora if bitacora is not None else BitacoraSegura(motor_pii=motor),
        )

    return _fabrica


def procesar_grupo(corrida_id: str, referencias: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    """Procesa como un solo lote los documentos de un grupo (un paciente, un episodio):
    la validación de episodio necesita verlos juntos. El mensaje transporta sólo
    referencias -- nunca contenido ni PII -- y no la ruta del directorio: si el
    trabajador enumerara la carpeta, un reintento sobre una carpeta que cambió
    procesaría otro grupo. `corrida_id` viaja como parámetro hermano, nunca como
    cuarta clave de la referencia."""
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


# Un extractor por etapas (CLASIFICADO -> EXTRAIDO_MINIMO -> ASOCIADO -> ...) se
# eliminó: nadie lo invocaba en src/, y no se comunicaba con EjecutorPipeline. La
# unidad de trabajo real es el GRUPO -- todo se procesa en una sola llamada síncrona.
# Reanudación de una corrida cortada: pendiente, a nivel de grupo, no de documento
# por etapa (fuera de alcance de esta limpieza).
