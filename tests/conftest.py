"""Fixtures compartidas de pytest. Todo dato de fixture debe ser sintético (ver AGENTS.md)."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

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
