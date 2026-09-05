"""Implementación real de `rutas_corridas.ServicioCorridas` (design.md, "ServicioCorridas real").

`crear_corrida` delega en `LanzadorCorrida` -- el despachador de producción
que encola los grupos sigue fuera de alcance (lo dejó fuera
`procesamiento-por-grupo`); lo que existe queda listo para él.
`consultar_corrida` lee el embudo real y mapea `documentos_pendientes` /
`cuarentenas` desde ahí, así que conserva `EstadoCorridaPortal` y con él los
tests de ruta con dobles de prueba. `reintentar_corrida` lanza
`NotImplementedError`: la reanudación por documento está fuera de alcance, y
la ruta ya funciona hoy -- un `POST` real llegaría a su rama y devolvería un
202 sobre algo que no reintenta nada. El 501 hace visible el hueco en vez de
disimularlo.

Este módulo también arma el payload completo de `GET /corridas/{id}/embudo`
(`construir_payload_embudo`): NO es un método de `ServicioCorridas` -- esa
ruta no pasa por el resumen agregado de `EstadoCorridaPortal`, sirve el
contrato JSON completo del embudo (design.md, "El contrato JSON").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
from anonimizacion.salida.modelos_orm import CorridaOrm
from anonimizacion.web.embudo_corrida import Embudo, construir_embudo
from anonimizacion.web.rutas_corridas import EstadoCorridaPortal


def _leer_estado_corrida(motor: Engine, id_corrida: str) -> str | None:
    """Sólo el estado administrativo (`corrida.estado`, plano de control).

    No es la misma prohibición que la de `documento_corrida.estado`
    (design.md, Decisión 5): esa es la máquina de estados del DOCUMENTO,
    nunca leída por el embudo. Ésta es el estado de la CORRIDA, una fila
    única de plano de control, y es lo que expone el campo `"estado"` del
    contrato JSON.
    """
    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, id_corrida)
    return fila.estado if fila is not None else None


def _serializar_embudo(embudo: Embudo, estado: str) -> dict[str, object]:
    estimacion: dict[str, object] = {"situacion": embudo.estimacion.situacion}
    if embudo.estimacion.situacion == "disponible":
        estimacion["restante_seg_min"] = embudo.estimacion.restante_seg_min
        estimacion["restante_seg_max"] = embudo.estimacion.restante_seg_max
    return {
        "corrida_id": embudo.corrida_id,
        "estado": estado,
        "generado_en": embudo.generado_en.isoformat(),
        "entraron": embudo.entraron,
        "publicados": embudo.publicados,
        "apartados": embudo.apartados,
        "residuo": embudo.residuo,
        "cierra": embudo.cierra,
        "marcha": embudo.marcha,
        "etapas": [
            {
                "etapa": perdida.etapa,
                "llegaron": perdida.llegaron,
                "apartados": perdida.apartados,
                "codigos": dict(perdida.codigos),
            }
            for perdida in embudo.etapas
        ],
        "throughput_por_hora": dict(embudo.throughput_por_hora),
        "estimacion": estimacion,
    }


def construir_payload_embudo(motor: Engine, id_corrida: str) -> dict[str, object] | None:
    """`None` si la corrida no existe -- la ruta lo traduce a 404."""
    estado = _leer_estado_corrida(motor, id_corrida)
    if estado is None:
        return None
    embudo = construir_embudo(motor, id_corrida)
    return _serializar_embudo(embudo, estado)


@dataclass(frozen=True)
class ServicioCorridasReal:
    """Implementación real: crea de verdad, consulta el embudo de verdad."""

    lanzador: LanzadorCorrida
    motor: Engine

    def crear_corrida(self, ruta_autorizada: str) -> EstadoCorridaPortal:
        resultado = self.lanzador.lanzar(Path(ruta_autorizada))
        return self.consultar_corrida(resultado.corrida_id)

    def consultar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
        estado = _leer_estado_corrida(self.motor, id_corrida)
        embudo = construir_embudo(self.motor, id_corrida)
        return EstadoCorridaPortal(
            id_corrida=id_corrida,
            estado=estado or "desconocida",
            # `sin_desenlace` es el mismo residuo con signo del embudo
            # (design.md, Decisión 9): no se recorta acá tampoco -- un
            # descuadre en la corrida real tiene que verse en este resumen
            # agregado igual que en el JSON completo.
            documentos_pendientes=embudo.residuo,
            cuarentenas=embudo.apartados,
        )

    def reintentar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
        raise NotImplementedError(
            "reintentar_corrida: la reanudacion por documento esta fuera de alcance de "
            "panel-de-operacion (design.md, 'ServicioCorridas real')"
        )
