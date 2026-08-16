"""Tests de `trabajadores/politica_reintentos.py` (tasks.md 9.1)."""

from __future__ import annotations

from anonimizacion.pipeline.ejecutor import BACKOFF_SEGUNDOS, MAX_REINTENTOS
from anonimizacion.trabajadores.politica_reintentos import OPCIONES_REINTENTO_CELERY


def test_reusa_las_mismas_constantes_que_pipeline_ejecutor() -> None:
    # no se duplica el número 5/30/180 en dos lugares (tasks.md 9.1)
    assert OPCIONES_REINTENTO_CELERY["max_retries"] == MAX_REINTENTOS == 3
    assert OPCIONES_REINTENTO_CELERY["retry_backoff_max"] == max(BACKOFF_SEGUNDOS) == 180


def test_backoff_segundos_es_5_30_180() -> None:
    assert BACKOFF_SEGUNDOS == (5, 30, 180)
