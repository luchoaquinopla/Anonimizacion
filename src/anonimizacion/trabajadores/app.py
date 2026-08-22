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

from anonimizacion.trabajadores.politica_reintentos import BACKOFF_SEGUNDOS, MAX_REINTENTOS

BROKER_URL_DEFAULT = "redis://localhost:6379/0"
RESULT_BACKEND_DEFAULT = "redis://localhost:6379/1"
CONCURRENCIA_DEFAULT = 4
CONCURRENCIA_MAXIMA = 16


def _variable_booleana(
    nombre: str, *, entorno: dict[str, str] | os._Environ[str] = os.environ, default: bool = False
) -> bool:
    valor = entorno.get(nombre)
    if valor is None:
        return default
    return valor.strip().lower() in ("1", "true", "yes", "on")


def _concurrencia_limitada(entorno: dict[str, str] | os._Environ[str]) -> int:
    try:
        valor = int(entorno.get("CELERY_WORKER_CONCURRENCY", str(CONCURRENCIA_DEFAULT)))
    except ValueError:
        return CONCURRENCIA_DEFAULT
    return min(max(valor, 1), CONCURRENCIA_MAXIMA)


def configuracion_cola(entorno: dict[str, str] | os._Environ[str]) -> dict[str, object]:
    """Configura límite, backpressure y redelivery ante caída del worker."""
    return {
        "task_default_queue": "anonimizacion",
        "worker_concurrency": _concurrencia_limitada(entorno),
        "worker_prefetch_multiplier": 1,
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "task_publish_retry": True,
        "task_publish_retry_policy": {
            "max_retries": MAX_REINTENTOS,
            "interval_start": BACKOFF_SEGUNDOS[0],
            "interval_step": BACKOFF_SEGUNDOS[1],
            "interval_max": BACKOFF_SEGUNDOS[-1],
        },
        "task_always_eager": _variable_booleana("CELERY_TASK_ALWAYS_EAGER", entorno=entorno),
        "task_eager_propagates": _variable_booleana("CELERY_TASK_ALWAYS_EAGER", entorno=entorno),
    }


app = Celery(
    "anonimizacion",
    broker=os.environ.get("CELERY_BROKER_URL", BROKER_URL_DEFAULT),
    backend=os.environ.get("CELERY_RESULT_BACKEND", RESULT_BACKEND_DEFAULT),
)


def aplicar_configuracion_cola(entorno: dict[str, str] | os._Environ[str]) -> None:
    """Aplica una configuración explícita al proceso worker actual."""
    app.conf.update(**configuracion_cola(entorno))


# Ver docstring del módulo: permite correr la suite de tests (y un dev sin
# Redis instalado) sin un broker real.
aplicar_configuracion_cola(os.environ)
