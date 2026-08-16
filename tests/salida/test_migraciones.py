"""Test de la migración Alembic (tasks.md 7.1) contra SQLite (spec `anonymized-output`).

Limitación de entorno de desarrollo (NO es una decisión de diseño): esta
máquina no tiene un servidor PostgreSQL corriendo ni `psycopg2` instalado
(verificado antes de empezar PR6). El dialecto de PRODUCCIÓN sigue siendo
Postgres (design.md, decisión Q1) -- este test corre la MISMA migración
contra SQLite en un archivo temporal, porque el DDL de
`migrations/versions/0001_esquema_inicial.py` usa únicamente tipos
portables (`sa.String`, `sa.Integer`, `sa.Float`, `sa.Boolean`, `sa.Date`,
`sa.DateTime`, y `sa.JSON().with_variant(JSONB(), "postgresql")` para las
columnas JSON) -- en Postgres esa columna compila a JSONB real; en SQLite
cae al `JSON` genérico de SQLAlchemy (columna `TEXT` con (de)serialización
automática). Ninguna columna JSON se usa como filtro/índice (design.md:
"JSONB... nunca como camino de acceso primario"), así que esa diferencia de
tipo no afecta ningún comportamiento ejercitado por los tests de esta fase.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

_RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
_TABLAS_ESPERADAS = {
    "vinculo_paciente",
    "episodio",
    "medicion_ecg",
    "resultado_laboratorio",
    "medicion_eco",
    "texto_seccion_eco",
    "cuarentena",
}


def _config_alembic(url_sqlite: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_RAIZ_REPO / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url_sqlite)
    return cfg


def test_migracion_head_crea_todas_las_tablas_del_esquema(tmp_path) -> None:
    ruta_db = tmp_path / "esquema_inicial.db"
    url = f"sqlite:///{ruta_db}"

    command.upgrade(_config_alembic(url), "head")

    motor = sa.create_engine(url)
    inspector = sa.inspect(motor)
    tablas = set(inspector.get_table_names())

    assert _TABLAS_ESPERADAS <= tablas


def test_migracion_downgrade_elimina_todas_las_tablas(tmp_path) -> None:
    ruta_db = tmp_path / "downgrade.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    motor = sa.create_engine(url)
    inspector = sa.inspect(motor)
    tablas = set(inspector.get_table_names())

    assert not (_TABLAS_ESPERADAS & tablas)


def test_metadata_orm_coincide_con_la_migracion(tmp_path) -> None:
    """El `Base.metadata` de `modelos_orm.py` describe exactamente las mismas tablas que la migración."""
    from anonimizacion.salida.modelos_orm import Base

    assert set(Base.metadata.tables.keys()) == _TABLAS_ESPERADAS
