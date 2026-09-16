"""Tests de `exportacion.py` contra Postgres real (revisión adversarial, CRÍTICO).

`-m postgres` estaba en 23 sin ningún test de exportación -- SQLite no puede
mostrar tres cosas que SÍ importan en producción: (a) `psycopg` puede
devolver `BYTEA` como `memoryview` en vez de `bytes`; (b) `estudio.adicionales`
es JSONB real, no el `TEXT` genérico de SQLite; (c) el nivel de aislamiento
`REPEATABLE READ` que pide `exportacion.py` sólo lo entiende Postgres.

Base ESCRATCH dedicada (mismo patrón que
`tests/salida/test_migraciones.py::_url_postgres_scratch`): una base NUEVA,
descartable, nunca la compartida `anonimizacion` de puerto 5433 -- se crea y
se destruye en este archivo, sin `alembic upgrade`/`downgrade` contra la base
compartida (regla dura del prompt)."""

from __future__ import annotations

import json
import socket
from datetime import date

import numpy as np
import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa

from anonimizacion.salida import exportacion as exportacion_modulo
from anonimizacion.salida.codec_senal import codificar_mascara, codificar_muestras
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.salida.exportacion import exportar_dataset
from anonimizacion.salida.modelos_orm import Base, Episodio, Estudio, SenalEcgOrm

_CONNECT_REAL = socket.socket.connect
_URL_POSTGRES_ADMIN = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
_NOMBRE_BASE_SCRATCH = "exportacion_scratch_test"


@pytest.fixture()
def _url_postgres_scratch_exportacion(monkeypatch: pytest.MonkeyPatch):
    """Base Postgres real DESCARTABLE, dedicada a este archivo -- nunca la
    base compartida `anonimizacion`. Mismo patrón (y mismo motivo de
    `connect_timeout`) que `tests/salida/test_migraciones.py::_url_postgres_scratch`."""
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    motor_admin = sa.create_engine(
        _URL_POSTGRES_ADMIN, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    try:
        with motor_admin.connect() as conexion:
            conexion.execute(sa.text(f"DROP DATABASE IF EXISTS {_NOMBRE_BASE_SCRATCH}"))
            conexion.execute(sa.text(f"CREATE DATABASE {_NOMBRE_BASE_SCRATCH}"))
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexión es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_ADMIN}: {excepcion}")

    url_scratch = _URL_POSTGRES_ADMIN.rsplit("/", 1)[0] + f"/{_NOMBRE_BASE_SCRATCH}"
    try:
        yield url_scratch
    finally:
        motor_admin.dispose()
        with sa.create_engine(
            _URL_POSTGRES_ADMIN, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
        ).connect() as conexion:
            conexion.execute(sa.text(f"DROP DATABASE IF EXISTS {_NOMBRE_BASE_SCRATCH}"))


@pytest.mark.postgres
def test_exportar_decodifica_senal_bytea_de_postgres_correctamente(
    _url_postgres_scratch_exportacion: str, tmp_path
) -> None:
    """psycopg3 puede devolver `BYTEA` como `memoryview` -- `decodificar_muestras`/
    `decodificar_mascara` deben funcionar igual (zlib/np.frombuffer aceptan el
    protocolo de buffer) y el Parquet debe salir con la forma y los valores
    EXACTOS de un oráculo escrito a mano, no sólo "no explota"."""
    engine = construir_engine_postgres(_url_postgres_scratch_exportacion)
    Base.metadata.create_all(engine)

    matriz = np.zeros((12, 5000), dtype=np.int16)
    for fila in range(12):
        matriz[fila, :] = (np.arange(5000) % 500 - 250).astype(np.int16) + fila
    mascara = np.zeros((12, 5000), dtype=bool)
    mascara[:, :2500] = True  # media señal enmascarada, para que la máscara no sea trivial

    with sa.orm.Session(engine) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio="ep-pg-1", id_paciente="pid-pg-1", fecha_ancla=date(2024, 4, 1)))
        estudio = Estudio(
            id_episodio="ep-pg-1",
            tipo_documento="ecg",
            fecha_estudio=date(2024, 4, 1),
            precision_hora="ausente",
            completo=True,
            campos_no_extraidos=[],
        )
        sesion.add(estudio)
        sesion.flush()
        sesion.add(
            SenalEcgOrm(
                id_estudio=estudio.id_estudio,
                muestras_uv=codificar_muestras(matriz),
                mascara=codificar_mascara(mascara),
                frecuencia_hz=500,
                version_extractor=1,
                version_formato=1,
            )
        )

    exportar_dataset(engine, tmp_path)
    engine.dispose()

    tabla = pq.read_table(tmp_path / "ecg.parquet")
    (muestras_planas,) = tabla.column("muestras_uv").to_pylist()
    (mascara_plana,) = tabla.column("mascara").to_pylist()
    exportado = np.array(muestras_planas, dtype=np.int16).reshape(12, 5000)
    mascara_exportada = np.array(mascara_plana, dtype=bool).reshape(12, 5000)

    assert np.array_equal(exportado, matriz)
    assert np.array_equal(mascara_exportada, mascara)


@pytest.mark.postgres
def test_exportar_conserva_estudio_adicionales_jsonb_con_las_mismas_claves_y_valores(
    _url_postgres_scratch_exportacion: str, tmp_path
) -> None:
    """`estudio.adicionales` es `JSONB` real en Postgres (`JSON().with_variant(JSONB(),
    "postgresql")`) -- en SQLite la capa ORM ya lo entrega deserializado y
    puede estar ocultando una diferencia real de tipos/round-trip (unicode,
    claves no-ASCII, anidamiento)."""
    engine = construir_engine_postgres(_url_postgres_scratch_exportacion)
    Base.metadata.create_all(engine)

    adicionales_oraculo = {
        "edad": "58",
        "institucion": "Instituto de Cardiología de Corrientes",
        "origen": "Consultorio Externo",
    }

    with sa.orm.Session(engine) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio="ep-pg-2", id_paciente="pid-pg-2", fecha_ancla=date(2024, 4, 2)))
        sesion.add(
            Estudio(
                id_episodio="ep-pg-2",
                tipo_documento="ecocardiograma",
                fecha_estudio=date(2024, 4, 2),
                precision_hora="ausente",
                completo=True,
                campos_no_extraidos=[],
                adicionales=adicionales_oraculo,
            )
        )

    exportar_dataset(engine, tmp_path)
    engine.dispose()

    tabla = pq.read_table(tmp_path / "eco.parquet")
    (adicionales_json,) = tabla.column("adicionales_json").to_pylist()
    assert json.loads(adicionales_json) == adicionales_oraculo


@pytest.mark.postgres
def test_exportar_usa_repeatable_read_de_verdad_y_no_ve_episodios_de_otra_conexion(
    _url_postgres_scratch_exportacion: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dos garantías en un solo test (evitar batería, instrucción del
    orquestador): (1) el nivel de aislamiento pedido en `exportacion.py` es
    real, verificado con `current_setting('transaction_isolation')` DENTRO de
    la transacción que abre `exportar_dataset`; (2) un episodio insertado por
    OTRA conexión, ya commiteado, DESPUÉS de que esa transacción tomó su
    snapshot, no es visible para una consulta posterior en la MISMA sesión --
    la garantía real de `REPEATABLE READ` (snapshot fijo para toda la
    transacción, no sólo para el primer `SELECT`)."""
    engine = construir_engine_postgres(_url_postgres_scratch_exportacion)
    Base.metadata.create_all(engine)

    with sa.orm.Session(engine) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio="ep-pg-3-antes", id_paciente="pid-pg-3-antes", fecha_ancla=date(2024, 4, 3)))

    nivel_observado: dict[str, str] = {}
    id_visible_de_mas: dict[str, bool] = {"valor": None}

    _original = exportacion_modulo._procesar_pagina

    def _procesar_pagina_espia(sesion, pagina_ids, escritores):
        # (1) nivel de aislamiento real, dentro de la MISMA transacción de exportación.
        nivel_observado["valor"] = sesion.execute(
            sa.text("SELECT current_setting('transaction_isolation')")
        ).scalar()

        # Inserta y COMMITEA desde una conexión totalmente separada, DESPUÉS
        # de que la transacción de exportación ya tomó su snapshot (la
        # transacción se abrió antes de llegar acá, en `exportar_dataset`).
        motor_externo = sa.create_engine(_url_postgres_scratch_exportacion)
        with sa.orm.Session(motor_externo) as sesion_externa, sesion_externa.begin():
            sesion_externa.add(
                Episodio(id_episodio="ep-pg-3-concurrente", id_paciente="pid-pg-3-concurrente", fecha_ancla=date(2024, 4, 3))
            )
        motor_externo.dispose()

        # (2) releer DENTRO de la misma transacción de exportación: el episodio
        # concurrente, ya commiteado por la otra conexión, no debe aparecer.
        ids_visibles = set(sesion.scalars(sa.select(Episodio.id_episodio)).all())
        id_visible_de_mas["valor"] = "ep-pg-3-concurrente" in ids_visibles

        return _original(sesion, pagina_ids, escritores)

    monkeypatch.setattr(exportacion_modulo, "_procesar_pagina", _procesar_pagina_espia)

    exportar_dataset(engine, tmp_path)
    engine.dispose()

    assert nivel_observado["valor"] == "repeatable read"
    assert id_visible_de_mas["valor"] is False, (
        "REPEATABLE READ debe mantener el snapshot fijo -- un episodio commiteado por "
        "otra conexion DESPUES de iniciar la transaccion no debe volverse visible"
    )

    tabla = pq.read_table(tmp_path / "episodios.parquet")
    ids_exportados = set(tabla.column("id_episodio").to_pylist())
    assert "ep-pg-3-concurrente" not in ids_exportados
    assert "ep-pg-3-antes" in ids_exportados
