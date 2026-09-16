"""Fija el esquema Arrow EXACTO (nombres, tipos y orden) de los 4 Parquet
exportados, leído desde disco -- y prueba de regresión del bug de pyarrow
que motivó el esquema de `muestras_uv`/`mascara`.

Los tipos esperados están escritos como LITERALES en este archivo, nunca
importados de `ESQUEMA_EPISODIOS`/`ESQUEMA_ECG`/`ESQUEMA_LABORATORIO`/
`ESQUEMA_ECO` (`salida/exportacion.py`) -- un test que compara el esquema
contra sí mismo es un espejo, no un oráculo (ya pasó tres veces en esta
cadena: ver `apply-progress.md`, entregas 1 y 3). `tests/salida/
test_exportacion.py` sólo fija los NOMBRES de columna (lista blanca de PII);
este archivo fija también el TIPO y el ORDEN, que es el contrato real con
`modelo_hvi` -- un cambio silencioso de `int16` a `int32`, o de lista
variable a lista fija, rompe al consumidor sin que ningún test lo note.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa

from anonimizacion.salida.codec_senal import codificar_mascara, codificar_muestras
from anonimizacion.salida.exportacion import exportar_dataset
from anonimizacion.salida.modelos_orm import (
    Base,
    Episodio,
    Estudio,
    MedicionEco,
    MedicionEcg,
    ResultadoLaboratorio,
    SenalEcgOrm,
    TextoSeccionEco,
)

_ESQUEMA_EPISODIOS_ESPERADO = [
    ("id_episodio", pa.string()),
    ("fecha_ancla", pa.date32()),
    ("tiene_ecg", pa.bool_()),
    ("tiene_laboratorio", pa.bool_()),
    ("tiene_eco", pa.bool_()),
    ("completo", pa.bool_()),
]

_ESQUEMA_ECG_ESPERADO = [
    ("id_episodio", pa.string()),
    ("fecha_estudio", pa.date32()),
    ("hora_estudio", pa.string()),
    ("completo", pa.bool_()),
    ("adicionales_json", pa.string()),
    ("vent_rate", pa.string()),
    ("pr_interval", pa.string()),
    ("qrs_duration", pa.string()),
    ("qt_qtc", pa.string()),
    ("ejes", pa.string()),
    ("tiene_senal", pa.bool_()),
    ("frecuencia_hz", pa.int32()),
    ("version_extractor", pa.int32()),
    ("version_formato", pa.int32()),
    # Lista de largo VARIABLE, no fija: pyarrow 25.0.1 no puede releer desde
    # Parquet una columna `fixed_size_list` cuando TODAS las filas de una
    # página son `None` (ver test de regresión más abajo).
    ("muestras_uv", pa.list_(pa.int16())),
    ("mascara", pa.list_(pa.bool_())),
]

_ESQUEMA_LABORATORIO_ESPERADO = [
    ("id_episodio", pa.string()),
    ("fecha_estudio", pa.date32()),
    ("completo", pa.bool_()),
    ("adicionales_json", pa.string()),
    ("analito", pa.string()),
    ("seccion", pa.string()),
    ("valor_num", pa.float64()),
    ("valor_texto", pa.string()),
    ("unidad", pa.string()),
    ("ref_min", pa.float64()),
    ("ref_max", pa.float64()),
]

_ESQUEMA_ECO_ESPERADO = [
    ("id_episodio", pa.string()),
    ("fecha_estudio", pa.date32()),
    ("completo", pa.bool_()),
    ("adicionales_json", pa.string()),
    ("ao", pa.string()),
    ("ai", pa.string()),
    ("ddvi", pa.string()),
    ("dsvi", pa.string()),
    ("fa", pa.string()),
    ("septum", pa.string()),
    ("p_posterior", pa.string()),
    ("unidades_json", pa.string()),
    ("medidas_extra_json", pa.string()),
]


@pytest.fixture()
def motor():
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def _senal_conocida() -> np.ndarray:
    matriz = np.zeros((12, 5000), dtype=np.int16)
    for fila in range(12):
        matriz[fila, :] = np.arange(5000, dtype=np.int16) + fila
    return matriz


def _poblar_episodio_completo(motor, *, id_episodio: str, id_paciente: str, fecha: date) -> None:
    with sa.orm.Session(motor) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio=id_episodio, id_paciente=id_paciente, fecha_ancla=fecha))

        estudio_ecg = Estudio(
            id_episodio=id_episodio,
            tipo_documento="ecg",
            fecha_estudio=fecha,
            precision_hora="ausente",
            completo=True,
            campos_no_extraidos=[],
            adicionales={"edad": "45"},
        )
        sesion.add(estudio_ecg)
        sesion.flush()
        senal = _senal_conocida()
        mascara = np.ones((12, 5000), dtype=bool)
        sesion.add(
            SenalEcgOrm(
                id_estudio=estudio_ecg.id_estudio,
                muestras_uv=codificar_muestras(senal),
                mascara=codificar_mascara(mascara),
                frecuencia_hz=500,
                version_extractor=1,
                version_formato=1,
            )
        )
        sesion.add(
            MedicionEcg(
                id_episodio=id_episodio,
                id_estudio=estudio_ecg.id_estudio,
                vent_rate="72",
                pr_interval="160",
                qrs_duration="90",
                qt_qtc="400/420",
                ejes="60/40/50",
            )
        )

        estudio_lab = Estudio(
            id_episodio=id_episodio,
            tipo_documento="laboratorio",
            fecha_estudio=fecha,
            precision_hora="ausente",
            completo=True,
            campos_no_extraidos=[],
            adicionales={"edad": "45"},
        )
        sesion.add(estudio_lab)
        sesion.flush()
        sesion.add(
            ResultadoLaboratorio(
                id_episodio=id_episodio,
                id_estudio=estudio_lab.id_estudio,
                analito="Hemoglobina",
                seccion="HEMATOLOGIA",
                valor_num=14.2,
                unidad="g/dL",
                ref_min=13.0,
                ref_max=17.0,
            )
        )

        estudio_eco = Estudio(
            id_episodio=id_episodio,
            tipo_documento="ecocardiograma",
            fecha_estudio=fecha,
            precision_hora="ausente",
            completo=True,
            campos_no_extraidos=[],
            adicionales={"peso": "80"},
        )
        sesion.add(estudio_eco)
        sesion.flush()
        sesion.add(
            MedicionEco(
                id_episodio=id_episodio,
                id_estudio=estudio_eco.id_estudio,
                ao="30",
                ai="35",
                unidades={"ao": "mm"},
                adicionales={"DDVFI": "50"},
            )
        )
        sesion.add(
            TextoSeccionEco(
                id_episodio=id_episodio, seccion="conclusiones", texto="motilidad conservada"
            )
        )


def _campos(tabla: pa.Table) -> list[tuple[str, pa.DataType]]:
    return [(campo.name, campo.type) for campo in tabla.schema]


def test_esquema_arrow_de_episodios_es_exacto_en_nombre_tipo_y_orden(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "episodios.parquet")
    assert _campos(tabla) == _ESQUEMA_EPISODIOS_ESPERADO


def test_esquema_arrow_de_ecg_es_exacto_en_nombre_tipo_y_orden(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "ecg.parquet")
    assert _campos(tabla) == _ESQUEMA_ECG_ESPERADO


def test_esquema_arrow_de_laboratorio_es_exacto_en_nombre_tipo_y_orden(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "laboratorio.parquet")
    assert _campos(tabla) == _ESQUEMA_LABORATORIO_ESPERADO


def test_esquema_arrow_de_eco_es_exacto_en_nombre_tipo_y_orden(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "eco.parquet")
    assert _campos(tabla) == _ESQUEMA_ECO_ESPERADO


def test_exportar_una_pagina_de_ecg_sin_ninguna_senal_capturada_hace_round_trip_correcto(
    motor, tmp_path
) -> None:
    """Regresión: pyarrow 25.0.1 fallaba con `ArrowInvalid: Expected all
    lists to be of size=N but index K had size=0` al releer `ecg.parquet`
    cuando TODAS las filas de la página tenían `muestras_uv`/`mascara` en
    `None` (columna `fixed_size_list`) -- caso real de una página cuyos ECG
    todavía no tienen señal capturada. Se corrigió usando lista de tamaño
    variable (ver esquema de arriba); este test puebla DOS episodios con ECG
    SIN señal (ninguna fila de `SenalEcgOrm`) y confirma que exportar y
    releer no explota, y que ambas filas siguen siendo `None`."""
    for indice, (id_episodio, id_paciente) in enumerate(
        (("ep-sin-senal-1", "pid-sin-senal-1"), ("ep-sin-senal-2", "pid-sin-senal-2"))
    ):
        with sa.orm.Session(motor) as sesion, sesion.begin():
            sesion.add(
                Episodio(
                    id_episodio=id_episodio,
                    id_paciente=id_paciente,
                    fecha_ancla=date(2024, 3, 1 + indice),
                )
            )
            sesion.add(
                Estudio(
                    id_episodio=id_episodio,
                    tipo_documento="ecg",
                    fecha_estudio=date(2024, 3, 1 + indice),
                    precision_hora="ausente",
                    completo=False,
                    campos_no_extraidos=["ecg.senal"],
                )
            )

    exportar_dataset(motor, tmp_path)  # no debe lanzar ArrowInvalid al escribir

    tabla = pq.read_table(tmp_path / "ecg.parquet")  # ni al releer

    assert tabla.num_rows == 2
    assert tabla.column("muestras_uv").to_pylist() == [None, None]
    assert tabla.column("mascara").to_pylist() == [None, None]
    assert tabla.column("tiene_senal").to_pylist() == [False, False]
