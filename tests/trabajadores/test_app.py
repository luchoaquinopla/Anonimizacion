"""Tests de `trabajadores/app.py` (tasks.md 9.1) -- config por variable de entorno."""

from __future__ import annotations

import importlib
import os

import pytest

from anonimizacion.trabajadores.app import configuracion_cola

_CLAVES_ENV = (
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "CELERY_TASK_ALWAYS_EAGER",
    "CELERY_WORKER_CONCURRENCY",
)


@pytest.fixture(autouse=True)
def _restaurar_environ():
    originales = {clave: os.environ.get(clave) for clave in _CLAVES_ENV}
    yield
    for clave, valor in originales.items():
        if valor is None:
            os.environ.pop(clave, None)
        else:
            os.environ[clave] = valor
    from anonimizacion.trabajadores import app as modulo_app

    importlib.reload(modulo_app)


def _recargar_app(env: dict[str, str]):
    for clave in _CLAVES_ENV:
        os.environ.pop(clave, None)
    os.environ.update(env)
    from anonimizacion.trabajadores import app as modulo_app

    return importlib.reload(modulo_app)


def test_default_de_broker_y_backend_es_redis_local() -> None:
    modulo = _recargar_app({})
    assert modulo.app.conf.broker_url == "redis://localhost:6379/0"
    assert modulo.app.conf.result_backend == "redis://localhost:6379/1"
    assert modulo.app.conf.task_always_eager is False


def test_variables_de_entorno_sobrescriben_el_default() -> None:
    modulo = _recargar_app(
        {
            "CELERY_BROKER_URL": "redis://otro-host:6379/5",
            "CELERY_RESULT_BACKEND": "redis://otro-host:6379/6",
            "CELERY_TASK_ALWAYS_EAGER": "1",
        }
    )
    assert modulo.app.conf.broker_url == "redis://otro-host:6379/5"
    assert modulo.app.conf.result_backend == "redis://otro-host:6379/6"
    assert modulo.app.conf.task_always_eager is True
    assert modulo.app.conf.task_eager_propagates is True


def test_configuracion_limita_concurrencia_y_activa_backpressure() -> None:
    configuracion = configuracion_cola({"CELERY_WORKER_CONCURRENCY": "100"})

    assert configuracion["worker_concurrency"] == 16
    assert configuracion["worker_prefetch_multiplier"] == 1
    assert configuracion["task_acks_late"] is True


def test_configuracion_hace_recuperable_un_fallo_del_worker() -> None:
    configuracion = configuracion_cola({"CELERY_WORKER_CONCURRENCY": "0"})

    assert configuracion["worker_concurrency"] == 1
    assert configuracion["task_reject_on_worker_lost"] is True
    assert configuracion["task_publish_retry"] is True
    assert configuracion["task_publish_retry_policy"] == {
        "max_retries": 3,
        "interval_start": 5,
        "interval_step": 30,
        "interval_max": 180,
    }


def test_configuracion_eager_usa_el_entorno_recibido() -> None:
    configuracion = configuracion_cola({"CELERY_TASK_ALWAYS_EAGER": "1"})

    assert configuracion["task_always_eager"] is True
    assert configuracion["task_eager_propagates"] is True
