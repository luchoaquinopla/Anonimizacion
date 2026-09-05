"""Fixtures compartidas de pytest. Todo dato de fixture debe ser sintético (ver AGENTS.md)."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

# Celery en modo eager para TODA la suite, no por modulo de test. Tiene que
# quedar seteado antes de que cualquier import construya la app: en cuanto un
# fixture importa `trabajadores/tareas.py` -- cosa que hace el banco de carga
# desde que se arma por la fabrica de produccion -- la app se configura con el
# broker real y `.delay()` intenta abrir una conexion a Redis, que el guardia de
# red de mas abajo bloquea. Ponerlo por modulo lo hacia depender del orden de
# recoleccion de pytest.
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")

import pytest

# permite correr tests sin instalación editable (layout `src`)
RAIZ_SRC = Path(__file__).resolve().parent.parent / "src"
if str(RAIZ_SRC) not in sys.path:
    sys.path.insert(0, str(RAIZ_SRC))


class LlamadaDeRedBloqueada(RuntimeError):
    """La suite de tests intentó abrir una conexión de red real -- ver tasks.md 11.5.

    Spec `pii-detection`/`pdf-text-extraction`: el pipeline es 100% offline en
    tiempo de ejecución (la única llamada de red legítima es la descarga
    *previa* del modelo spaCy, hecha una vez fuera de la suite -- ver
    `pii/motor.py`, docstring del módulo). Este bloqueo confirma esa garantía
    en toda la suite, no solo en los tests de `pii-detection`.
    """


@pytest.fixture(autouse=True, scope="session")
def _bloquear_llamadas_de_red_reales():
    """Parchea `socket.socket.connect` para toda la sesión de tests (tasks.md 11.5).

    `sqlite:///:memory:`/`sqlite:///archivo.db` (SQLAlchemy) y la carga de
    spaCy/Presidio desde disco NO usan `socket.connect` -- son I/O local, no
    de red -- así que este bloqueo no afecta a ningún test existente; solo
    lanza si algo intenta abrir una conexión TCP/UDP real.
    """
    original_connect = socket.socket.connect

    def _connect_bloqueado(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise LlamadaDeRedBloqueada(
            "Intento de conexión de red real bloqueado en la suite de tests (tasks.md 11.5)"
        )

    socket.socket.connect = _connect_bloqueado
    try:
        yield
    finally:
        socket.socket.connect = original_connect
