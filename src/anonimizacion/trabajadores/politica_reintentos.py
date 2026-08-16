"""Política de reintentos compartida por Celery y `pipeline/ejecutor.py` (tasks.md 9.1).

Backoff fijo 5s/30s/180s, 3 reintentos tras el intento inicial (ver
design.md, "Aislamiento de fallo y política de reintentos"). Única fuente de
verdad: `BACKOFF_SEGUNDOS`/`MAX_REINTENTOS` viven en `pipeline/ejecutor.py`
(Fase 8, implementada primero); este módulo los reimporta y los expone en el
formato que espera un `@app.task(...)` de Celery, para no declarar los
mismos tres números en dos lugares distintos.

Nota de arquitectura: `EjecutorPipeline` (Fase 8) YA reintenta errores
transitorios internamente, de forma síncrona, antes de devolver un
`ResultadoDocumento` -- ver `pipeline/ejecutor.py::_ejecutar_con_reintentos`.
Por eso `trabajadores/tareas.py` NO usa `autoretry_for` (que reintentaría
también fallos determinísticos si algo inesperado se escapara del ejecutor,
violando la regla de "nunca reintentar `ErrorParseo`"): `OPCIONES_REINTENTO_CELERY`
queda como config de referencia/defensa en profundidad para quien arme la
tarea de Celery, no un mecanismo automático de reintento del framework.
"""

from __future__ import annotations

from anonimizacion.pipeline.ejecutor import BACKOFF_SEGUNDOS, MAX_REINTENTOS

__all__ = ["BACKOFF_SEGUNDOS", "MAX_REINTENTOS", "OPCIONES_REINTENTO_CELERY"]

OPCIONES_REINTENTO_CELERY: dict[str, object] = {
    "max_retries": MAX_REINTENTOS,
    "retry_backoff": True,
    "retry_backoff_max": max(BACKOFF_SEGUNDOS),
    "retry_jitter": False,
}
