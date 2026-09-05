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
    "estudio",
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


def test_indices_y_restricciones_unicas_del_orm_coinciden_con_la_migracion(tmp_path) -> None:
    """`Base.metadata.create_all()` y Alembic son DOS caminos que producen el
    esquema (la mayoría de `tests/salida/` usa el primero; producción usa el
    segundo). Si divergen, un `create_all` en test corre contra un esquema
    distinto del real, y un futuro `alembic revision --autogenerate` puede
    "corregir" la divergencia deshaciendo en silencio una decisión de diseño
    -- exactamente lo que pasó con `ix_documento_corrida_corrida_id`: la
    migración 0008 lo elimina (redundante con el prefijo de
    `uq_documento_corrida_huella`) pero el modelo ORM seguía declarándolo.
    """
    from anonimizacion.salida.modelos_orm import Base

    url_alembic = f"sqlite:///{tmp_path / 'via_alembic.db'}"
    command.upgrade(_config_alembic(url_alembic), "head")
    inspector_alembic = sa.inspect(sa.create_engine(url_alembic))

    url_orm = f"sqlite:///{tmp_path / 'via_orm.db'}"
    motor_orm = sa.create_engine(url_orm)
    Base.metadata.create_all(motor_orm)
    inspector_orm = sa.inspect(motor_orm)

    for tabla in sorted(_TABLAS_ESPERADAS):
        indices_alembic = {indice["name"] for indice in inspector_alembic.get_indexes(tabla)}
        indices_orm = {indice["name"] for indice in inspector_orm.get_indexes(tabla)}
        assert indices_orm == indices_alembic, (
            f"{tabla}: índices del ORM ({indices_orm}) no coinciden con los de la "
            f"migración ({indices_alembic})"
        )

        unicas_alembic = {r["name"] for r in inspector_alembic.get_unique_constraints(tabla)}
        unicas_orm = {r["name"] for r in inspector_orm.get_unique_constraints(tabla)}
        assert unicas_orm == unicas_alembic, (
            f"{tabla}: restricciones únicas del ORM ({unicas_orm}) no coinciden con "
            f"las de la migración ({unicas_alembic})"
        )



def test_migraciones_tienen_una_unica_cabecera() -> None:
    script = ScriptDirectory.from_config(_config_alembic("sqlite://"))

    assert len(script.get_heads()) == 1


def test_migracion_estudio_agrega_fk_nullable_en_las_tres_mediciones(tmp_path) -> None:
    """SQLite no soporta `ALTER TABLE` con FK: la migración usa `batch_alter_table`."""
    ruta_db = tmp_path / "estudio_fk.db"
    url = f"sqlite:///{ruta_db}"

    command.upgrade(_config_alembic(url), "head")

    inspector = sa.inspect(sa.create_engine(url))
    for tabla in ("medicion_ecg", "resultado_laboratorio", "medicion_eco"):
        columnas = {columna["name"]: columna for columna in inspector.get_columns(tabla)}
        assert "id_estudio" in columnas, f"{tabla} no recibio la FK id_estudio"
        assert columnas["id_estudio"]["nullable"] is True, f"{tabla}.id_estudio debe ser nullable"

    columnas_estudio = {columna["name"] for columna in inspector.get_columns("estudio")}
    assert {"id_estudio", "id_episodio", "tipo_documento", "fecha_estudio", "hora_estudio", "precision_hora"} <= (
        columnas_estudio
    )


def test_downgrade_de_estudio_vuelve_al_esquema_anterior(tmp_path) -> None:
    ruta_db = tmp_path / "estudio_downgrade.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0005_tamano_y_tope_cuarentena")

    inspector = sa.inspect(sa.create_engine(url))
    assert "estudio" not in set(inspector.get_table_names())
    for tabla in ("medicion_ecg", "resultado_laboratorio", "medicion_eco"):
        columnas = {columna["name"] for columna in inspector.get_columns(tabla)}
        assert "id_estudio" not in columnas, f"{tabla} conservo la FK tras el downgrade"


def test_ciclo_upgrade_downgrade_upgrade_es_estructuralmente_idempotente(tmp_path) -> None:
    ruta_db = tmp_path / "estudio_ciclo.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0005_tamano_y_tope_cuarentena")
    command.upgrade(cfg, "head")

    inspector = sa.inspect(sa.create_engine(url))
    assert "estudio" in set(inspector.get_table_names())
    for tabla in ("medicion_ecg", "resultado_laboratorio", "medicion_eco"):
        assert "id_estudio" in {columna["name"] for columna in inspector.get_columns(tabla)}


def test_migracion_clave_documento_agrega_columna_y_restriccion_unica(tmp_path) -> None:
    ruta_db = tmp_path / "clave_documento.db"
    url = f"sqlite:///{ruta_db}"

    command.upgrade(_config_alembic(url), "head")

    inspector = sa.inspect(sa.create_engine(url))
    columnas = {columna["name"]: columna for columna in inspector.get_columns("estudio")}
    assert "clave_documento" in columnas
    assert columnas["clave_documento"]["nullable"] is True

    restricciones = {r["name"] for r in inspector.get_unique_constraints("estudio")}
    assert "uq_estudio_clave_documento" in restricciones


def test_downgrade_de_clave_documento_vuelve_al_esquema_anterior(tmp_path) -> None:
    ruta_db = tmp_path / "clave_documento_down.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0006_estudio_y_hora")

    inspector = sa.inspect(sa.create_engine(url))
    columnas = {columna["name"] for columna in inspector.get_columns("estudio")}
    assert "clave_documento" not in columnas


def test_ciclo_completo_de_clave_documento_es_estructuralmente_idempotente(tmp_path) -> None:
    ruta_db = tmp_path / "clave_documento_ciclo.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0006_estudio_y_hora")
    command.upgrade(cfg, "head")

    inspector = sa.inspect(sa.create_engine(url))
    assert "clave_documento" in {c["name"] for c in inspector.get_columns("estudio")}


# --- 0008_corrida_en_salida: corrida_id en estudio y cuarentena --------------


def test_migracion_0008_agrega_corrida_id_en_estudio_y_cuarentena(tmp_path) -> None:
    ruta_db = tmp_path / "corrida_en_salida.db"
    url = f"sqlite:///{ruta_db}"

    command.upgrade(_config_alembic(url), "head")

    inspector = sa.inspect(sa.create_engine(url))

    columnas_estudio = {columna["name"]: columna for columna in inspector.get_columns("estudio")}
    assert "corrida_id" in columnas_estudio
    assert columnas_estudio["corrida_id"]["nullable"] is True
    assert "creado_en" in columnas_estudio
    assert columnas_estudio["creado_en"]["nullable"] is True

    indices_estudio = {indice["name"] for indice in inspector.get_indexes("estudio")}
    assert "ix_estudio_corrida_creado" in indices_estudio

    columnas_cuarentena = {columna["name"]: columna for columna in inspector.get_columns("cuarentena")}
    assert "corrida_id" in columnas_cuarentena
    assert columnas_cuarentena["corrida_id"]["nullable"] is True

    restricciones_cuarentena = {r["name"] for r in inspector.get_unique_constraints("cuarentena")}
    assert "uq_cuarentena_corrida_documento" in restricciones_cuarentena

    indices_cuarentena = {indice["name"] for indice in inspector.get_indexes("cuarentena")}
    assert "ix_cuarentena_corrida_creado" in indices_cuarentena

    indices_documento_corrida = {indice["name"] for indice in inspector.get_indexes("documento_corrida")}
    assert "ix_documento_corrida_corrida_id" not in indices_documento_corrida, (
        "redundante con uq_documento_corrida_huella -- ver design.md"
    )


def test_migracion_0008_conserva_duplicados_preexistentes_de_cuarentena(tmp_path) -> None:
    """Fija el punto de partida real: hay duplicados de `id_documento` sin
    corrida en el sistema hoy (ningún reintento de Celery tenía restricción
    que lo impidiera). La migración 0008 no los toca -- ver design.md,
    Decisión 4: los `NULL` no colisionan entre sí, así que la restricción
    única se crea sobre ellos sin deduplicar ni rellenar nada."""
    ruta_db = tmp_path / "duplicados_previos.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "0007_clave_documento")

    motor = sa.create_engine(url)
    with motor.begin() as conexion:
        for _ in range(2):
            conexion.execute(
                sa.text(
                    "INSERT INTO cuarentena (id_documento, etapa, codigo, creado_en) "
                    "VALUES ('doc-duplicado', 'parseo', 'parseo_incompleto', :ahora)"
                ),
                {"ahora": "2026-01-01T00:00:00+00:00"},
            )

    command.upgrade(cfg, "head")

    motor = sa.create_engine(url)
    inspector = sa.inspect(motor)
    columnas_cuarentena = {columna["name"] for columna in inspector.get_columns("cuarentena")}
    assert "corrida_id" in columnas_cuarentena, "0008 debe agregar corrida_id sin tocar filas existentes"

    with motor.connect() as conexion:
        total = conexion.execute(
            sa.text("SELECT count(*) FROM cuarentena WHERE id_documento = 'doc-duplicado'")
        ).scalar_one()
    assert total == 2, "la migracion no debe deduplicar ni rellenar nada sobre filas preexistentes"


def test_downgrade_de_0008_vuelve_al_esquema_de_clave_documento(tmp_path) -> None:
    ruta_db = tmp_path / "corrida_en_salida_downgrade.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0007_clave_documento")

    inspector = sa.inspect(sa.create_engine(url))

    columnas_estudio = {columna["name"] for columna in inspector.get_columns("estudio")}
    assert "corrida_id" not in columnas_estudio
    assert "creado_en" not in columnas_estudio

    columnas_cuarentena = {columna["name"] for columna in inspector.get_columns("cuarentena")}
    assert "corrida_id" not in columnas_cuarentena

    restricciones_cuarentena = {r["name"] for r in inspector.get_unique_constraints("cuarentena")}
    assert "uq_cuarentena_corrida_documento" not in restricciones_cuarentena

    indices_documento_corrida = {indice["name"] for indice in inspector.get_indexes("documento_corrida")}
    assert "ix_documento_corrida_corrida_id" in indices_documento_corrida, (
        "downgrade debe restaurar el indice que 0008 elimino"
    )


def test_ciclo_upgrade_downgrade_upgrade_de_0008_es_estructuralmente_idempotente(tmp_path) -> None:
    ruta_db = tmp_path / "corrida_en_salida_ciclo.db"
    url = f"sqlite:///{ruta_db}"
    cfg = _config_alembic(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0007_clave_documento")
    command.upgrade(cfg, "head")

    inspector = sa.inspect(sa.create_engine(url))
    columnas_estudio = {columna["name"] for columna in inspector.get_columns("estudio")}
    assert "corrida_id" in columnas_estudio
    assert "creado_en" in columnas_estudio

    columnas_cuarentena = {columna["name"] for columna in inspector.get_columns("cuarentena")}
    assert "corrida_id" in columnas_cuarentena

    restricciones_cuarentena = {r["name"] for r in inspector.get_unique_constraints("cuarentena")}
    assert "uq_cuarentena_corrida_documento" in restricciones_cuarentena

