"""Fixtures de la red de caracterización (Entrega 0, `auditoria-y-poda`).

`engine_caracterizacion` crea una base Postgres EFÍMERA y descartable por
test (`caracterizacion_<uuid>`) -- nunca toca la base compartida del puerto
5433 (`design.md`, D1 "Aislamiento de la base"). Mismo patrón que
`tests/salida/test_migraciones.py::_url_postgres_scratch`, con un nombre por
test (no un scratch fijo) para poder correr en paralelo sin colisionar con
un colega.
"""

from __future__ import annotations

import socket
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

# Capturado ANTES de que `tests/conftest.py::_bloquear_llamadas_de_red_reales`
# (autouse, scope de sesión) parchee `socket.socket.connect` -- mismo patrón
# que `tests/salida/test_migraciones.py`/`tests/integracion/test_postgres_carrera_real.py`.
_CONNECT_REAL = socket.socket.connect
_URL_POSTGRES_ADMIN = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"

_RAIZ_REPO = Path(__file__).resolve().parent.parent.parent


def _config_alembic(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_RAIZ_REPO / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture()
def engine_caracterizacion(monkeypatch: pytest.MonkeyPatch):
    """`CREATE DATABASE caracterizacion_<uuid>` -> `alembic upgrade head` -> yield engine -> `DROP DATABASE`.

    `pytest.skip` si Postgres real no responde (mismo criterio que el resto
    de la suite marcada `postgres`).
    """
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    nombre_base = f"caracterizacion_{uuid.uuid4().hex[:12]}"
    motor_admin = sa.create_engine(
        _URL_POSTGRES_ADMIN, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    try:
        with motor_admin.connect() as conexion:
            conexion.execute(sa.text(f"CREATE DATABASE {nombre_base}"))
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexión es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_ADMIN}: {excepcion}")

    url_base = _URL_POSTGRES_ADMIN.rsplit("/", 1)[0] + f"/{nombre_base}"
    try:
        command.upgrade(_config_alembic(url_base), "head")
        engine = sa.create_engine(url_base)
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        with motor_admin.connect() as conexion:
            conexion.execute(sa.text(f"DROP DATABASE IF EXISTS {nombre_base}"))
        motor_admin.dispose()
