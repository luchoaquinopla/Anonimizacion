"""Entrypoint de Alembic. `target_metadata` apunta al `Base` declarativo de
`anonimizacion.salida.modelos_orm` (fuente de verdad del esquema); la
revisión `0001_esquema_inicial.py` está escrita a mano (no autogenerada)
para que el DDL sea determinístico y no dependa de tener un Postgres real
corriendo para poder desarrollarla (ver tests/salida/test_migraciones.py:
el entorno de desarrollo de este repo no tiene Postgres instalado).
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

_RAIZ_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_RAIZ_SRC) not in sys.path:
    sys.path.insert(0, str(_RAIZ_SRC))

from anonimizacion.salida.modelos_orm import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
