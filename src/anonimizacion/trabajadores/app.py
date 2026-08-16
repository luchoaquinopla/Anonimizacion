"""Instancia de Celery del pipeline (tasks.md 9.1).

Broker/backend parametrizables por variable de entorno
(`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`), con Redis local como default
razonable para producción -- documentado acá, no hardcodeado como credencial
real (ninguna URL con secretos vive en el repo; el default es un endpoint de
desarrollo).

LIMITACIÓN DE ENTORNO (dev, esta máquina, ver mismo patrón que
`salida/destinos/postgres.py` en PR6): no hay Redis instalado/corriendo acá.
Celery soporta correr tareas de forma síncrona sin un broker real vía
`task_always_eager` -- se activa poniendo `CELERY_TASK_ALWAYS_EAGER=1` (los
tests de `trabajadores/test_tareas.py` lo hacen explícitamente). En modo
eager, `app` nunca abre una conexión de red real, así que la ausencia de
Redis en esta máquina no bloquea los tests. La URL Redis de producción sigue
siendo la decisión correcta por design.md (stack: celery, redis).
"""

from __future__ import annotations

import os

from celery import Celery

BROKER_URL_DEFAULT = "redis://localhost:6379/0"
RESULT_BACKEND_DEFAULT = "redis://localhost:6379/1"


def _variable_booleana(nombre: str, *, default: bool = False) -> bool:
    valor = os.environ.get(nombre)
    if valor is None:
        return default
    return valor.strip().lower() in ("1", "true", "yes", "on")


app = Celery(
    "anonimizacion",
    broker=os.environ.get("CELERY_BROKER_URL", BROKER_URL_DEFAULT),
    backend=os.environ.get("CELERY_RESULT_BACKEND", RESULT_BACKEND_DEFAULT),
)

# Ver docstring del módulo: permite correr la suite de tests (y un dev sin
# Redis instalado) sin un broker real.
app.conf.task_always_eager = _variable_booleana("CELERY_TASK_ALWAYS_EAGER")
app.conf.task_eager_propagates = app.conf.task_always_eager
