"""Test de contrato con el consumidor `modelo-hvi` (tasks.md 3.4).

`modelo-hvi` NUNCA se importa acá (repo separado, sólo lectura permitida por
el prompt) -- los números de contrato son LITERALES medidos contra
`modelo_hvi/formato_unico.py::EsquemaPdf` (HZ=250, MUESTRAS=2500,
muestras_por_tramo=619, inicio_columna_s=(0, 2.5, 5, 7.5)), no importados de
ningún lado. Ver spec `exportacion-dataset-vinculado`, escenario "Consumidor
decimando ×2".
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa

from anonimizacion.salida.codec_senal import codificar_mascara, codificar_muestras
from anonimizacion.salida.exportacion import exportar_dataset
from anonimizacion.salida.modelos_orm import Base, Episodio, Estudio, SenalEcgOrm

# Literales medidos de `modelo_hvi/formato_unico.py::EsquemaPdf` -- NUNCA importados.
_HZ_CONSUMIDOR = 250
_MUESTRAS_CONSUMIDOR = 2500
_MUESTRAS_POR_TRAMO_CONSUMIDOR = 619
_INICIO_COLUMNA_S_CONSUMIDOR = (0.0, 2.5, 5.0, 7.5)
_DERIVACION_RITMO_CONSUMIDOR = "V1"
_INDICE_V1 = 6  # ORDEN_DERIVACIONES: I,II,III,aVR,aVL,aVF,V1,...


@pytest.fixture()
def motor():
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def test_decimar_x2_la_senal_exportada_da_619_muestras_por_tramo_y_v1_completa(motor, tmp_path) -> None:
    matriz = np.zeros((12, 5000), dtype=np.int16)
    for fila in range(12):
        matriz[fila, :] = (np.arange(5000) % 1000).astype(np.int16) + fila
    mascara = np.ones((12, 5000), dtype=bool)

    with sa.orm.Session(motor) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10)))
        estudio = Estudio(
            id_episodio="ep-1",
            tipo_documento="ecg",
            fecha_estudio=date(2024, 1, 10),
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

    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "ecg.parquet")
    (muestras_planas,) = tabla.column("muestras_uv").to_pylist()
    exportado = np.array(muestras_planas, dtype=np.int16).reshape(12, 5000)

    # "Decimar ×2" y ninguna otra transformación: tomar una de cada dos muestras.
    decimado = exportado[:, ::2]
    assert decimado.shape == (12, _MUESTRAS_CONSUMIDOR)

    for indice_columna, inicio_s in enumerate(_INICIO_COLUMNA_S_CONSUMIDOR):
        inicio_muestra = round(inicio_s * _HZ_CONSUMIDOR)
        fin_muestra = inicio_muestra + _MUESTRAS_POR_TRAMO_CONSUMIDOR
        tramo = decimado[0, inicio_muestra:fin_muestra]  # derivación I, columna 0 en la grilla
        if indice_columna == 0:
            assert tramo.shape == (_MUESTRAS_POR_TRAMO_CONSUMIDOR,)

    # V1 (tira de ritmo): la derivación COMPLETA, sin recorte por tramo.
    v1_decimada = decimado[_INDICE_V1, :]
    assert v1_decimada.shape == (_MUESTRAS_CONSUMIDOR,)
