"""Pruebas de migraciones Alembic contra SQLite, incluido el estado durable de corridas."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

_RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
_TABLAS_ESPERADAS = {
    "vinculo_paciente",
    "episodio",
    "medicion_ecg",
    "resultado_laboratorio",
    "medicion_eco",
    "texto_seccion_eco",
    "cuarentena",
    "corrida",
    "documento_corrida",
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


def test_migracion_persiste_corrida_y_documento_idempotente(tmp_path) -> None:
    ruta_db = tmp_path / "corridas.db"
    url = f"sqlite:///{ruta_db}"
    command.upgrade(_config_alembic(url), "head")

    motor = sa.create_engine(url)
    with motor.begin() as conexion:
        conexion.execute(
            sa.text("INSERT INTO corrida (id_corrida, estado, version) VALUES ('corrida-1', 'creada', 0)")
        )
        conexion.execute(
            sa.text(
                "INSERT INTO documento_corrida "
                "(corrida_id, huella_contenido, ruta_autorizada, estado, version) "
                "VALUES ('corrida-1', :huella, 'entrada/estudio.pdf', 'inventariado', 0)"
            ),
            {"huella": "a" * 64},
        )

    with motor.begin() as conexion:
        with pytest.raises(sa.exc.IntegrityError):
            conexion.execute(
                sa.text(
                    "INSERT INTO documento_corrida "
                    "(corrida_id, huella_contenido, ruta_autorizada, estado, version) "
                    "VALUES ('corrida-1', :huella, 'entrada/repetido.pdf', 'inventariado', 0)"
                ),
                {"huella": "a" * 64},
            )


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
    from anonimizacion.salida.modelos_orm import Base

    assert set(Base.metadata.tables.keys()) == _TABLAS_ESPERADAS



def test_migraciones_tienen_una_unica_cabecera() -> None:
    script = ScriptDirectory.from_config(_config_alembic("sqlite://"))

    assert len(script.get_heads()) == 1
