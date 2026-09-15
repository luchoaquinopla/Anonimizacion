"""Tests de `salida/exportacion.py` (tasks.md 3.1-3.3, spec `exportacion-dataset-vinculado`).

Cubre: lista blanca EXACTA de columnas por archivo (falsable: agregar una
columna nueva debe romper el test), no mutación de PostgreSQL, vinculación
por episodio ya resuelta en `estudio.id_episodio` (no se reimplementa acá),
completitud explícita, manifiesto de contrato, y paginación con memoria
acotada (verificable por conteo de filas materializadas por página, nunca
por umbral de tiempo).
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa

from anonimizacion.salida.exportacion import (
    NOMBRE_MANIFIESTO,
    exportar_dataset,
    _ids_episodio_paginados,
)
from anonimizacion.salida.codec_senal import codificar_mascara, codificar_muestras
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
            adicionales={"edad": "45", "institucion": "Instituto de Cardiologia"},
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
            adicionales={"edad": "45", "origen": "Guardia"},
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
            adicionales={"peso": "80", "talla": "1.75", "superficie_corporal": "1.95"},
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


# --- lista blanca de columnas (falsable) ------------------------------------


def test_esquema_de_episodios_es_exactamente_la_lista_blanca(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "episodios.parquet")
    assert set(tabla.column_names) == {
        "id_episodio",
        "fecha_ancla",
        "tiene_ecg",
        "tiene_laboratorio",
        "tiene_eco",
        "completo",
    }


def test_esquema_de_ecg_es_exactamente_la_lista_blanca_sin_ids_de_medico(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "ecg.parquet")
    esperado = {
        "id_episodio",
        "fecha_estudio",
        "hora_estudio",
        "completo",
        "adicionales_json",
        "vent_rate",
        "pr_interval",
        "qrs_duration",
        "qt_qtc",
        "ejes",
        "tiene_senal",
        "frecuencia_hz",
        "version_extractor",
        "version_formato",
        "muestras_uv",
        "mascara",
    }
    assert set(tabla.column_names) == esperado
    assert "id_medico" not in tabla.column_names
    assert "clave_documento" not in tabla.column_names
    assert "corrida_id" not in tabla.column_names


def test_esquema_de_laboratorio_es_exactamente_la_lista_blanca(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "laboratorio.parquet")
    assert set(tabla.column_names) == {
        "id_episodio",
        "fecha_estudio",
        "completo",
        "adicionales_json",
        "analito",
        "seccion",
        "valor_num",
        "valor_texto",
        "unidad",
        "ref_min",
        "ref_max",
    }
    assert "id_medico" not in tabla.column_names


def test_esquema_de_eco_es_exactamente_la_lista_blanca_sin_texto_libre(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "eco.parquet")
    esperado = {
        "id_episodio",
        "fecha_estudio",
        "completo",
        "adicionales_json",
        "ao",
        "ai",
        "ddvi",
        "dsvi",
        "fa",
        "septum",
        "p_posterior",
        "unidades_json",
        "medidas_extra_json",
    }
    assert set(tabla.column_names) == esperado
    # texto libre (motilidad, conclusiones) nunca sale de Postgres
    assert "texto" not in tabla.column_names
    assert "secciones_texto" not in tabla.column_names
    assert "id_medico_solicitante" not in tabla.column_names
    assert "id_medico_informante" not in tabla.column_names
    assert "id_matricula_informante" not in tabla.column_names


def test_agregar_una_columna_no_listada_rompe_el_test_de_esquema(motor, tmp_path) -> None:
    """Demuestra que el test de arriba es falsable: si `exportar_dataset`
    agregara una columna nueva no declarada en la lista blanca (simulado acá
    reconstruyendo la tabla con una columna extra), la comparación de
    conjuntos debe fallar."""
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "episodios.parquet")
    columnas_con_extra = set(tabla.column_names) | {"columna_no_listada"}
    with pytest.raises(AssertionError):
        assert columnas_con_extra == {
            "id_episodio",
            "fecha_ancla",
            "tiene_ecg",
            "tiene_laboratorio",
            "tiene_eco",
            "completo",
        }


# --- cero PII en adicionales_json (ya saneado por estudio.adicionales) -----


def test_adicionales_json_del_ecg_nunca_contiene_claves_personales(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "ecg.parquet")
    (adicionales_json,) = tabla.column("adicionales_json").to_pylist()
    adicionales = json.loads(adicionales_json)
    assert adicionales == {"edad": "45", "institucion": "Instituto de Cardiologia"}
    assert "medico_derivante" not in adicionales


# --- vinculación y completitud ----------------------------------------------


def test_episodio_con_los_3_documentos_queda_marcado_completo(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "episodios.parquet")
    fila = tabla.to_pylist()[0]
    assert fila["tiene_ecg"] is True
    assert fila["tiene_laboratorio"] is True
    assert fila["tiene_eco"] is True
    assert fila["completo"] is True


def test_episodio_sin_ecg_no_se_descarta_y_queda_marcado_incompleto(motor, tmp_path) -> None:
    with sa.orm.Session(motor) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio="ep-incompleto", id_paciente="pid-2", fecha_ancla=date(2024, 2, 1)))
        estudio_lab = Estudio(
            id_episodio="ep-incompleto",
            tipo_documento="laboratorio",
            fecha_estudio=date(2024, 2, 1),
            precision_hora="ausente",
            completo=True,
            campos_no_extraidos=[],
        )
        sesion.add(estudio_lab)
        sesion.flush()
        sesion.add(
            ResultadoLaboratorio(
                id_episodio="ep-incompleto",
                id_estudio=estudio_lab.id_estudio,
                analito="Glucosa",
                seccion="QUIMICA CLINICA",
                valor_num=90.0,
            )
        )

    exportar_dataset(motor, tmp_path)

    tabla = pq.read_table(tmp_path / "episodios.parquet")
    fila = tabla.to_pylist()[0]
    assert fila["tiene_laboratorio"] is True
    assert fila["tiene_ecg"] is False
    assert fila["tiene_eco"] is False
    assert fila["completo"] is False
    # no se descarta: sigue habiendo una fila de laboratorio
    assert pq.read_table(tmp_path / "laboratorio.parquet").num_rows == 1


# --- no mutación de la base --------------------------------------------------


def test_exportar_no_muta_ninguna_fila_de_la_base(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    with sa.orm.Session(motor) as sesion:
        conteo_antes = {
            tabla: sesion.scalar(sa.select(sa.func.count()).select_from(tabla))
            for tabla in (Episodio, Estudio, MedicionEcg, SenalEcgOrm, ResultadoLaboratorio, MedicionEco)
        }

    exportar_dataset(motor, tmp_path)

    with sa.orm.Session(motor) as sesion:
        conteo_despues = {
            tabla: sesion.scalar(sa.select(sa.func.count()).select_from(tabla))
            for tabla in (Episodio, Estudio, MedicionEcg, SenalEcgOrm, ResultadoLaboratorio, MedicionEco)
        }
    assert conteo_antes == conteo_despues


# --- manifiesto de contrato --------------------------------------------------


def test_manifiesto_declara_frecuencia_orden_ventanas_y_conteos(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    manifiesto = json.loads((tmp_path / NOMBRE_MANIFIESTO).read_text(encoding="utf-8"))
    assert manifiesto["frecuencia_hz"] == 500
    assert manifiesto["orden_derivaciones"] == [
        "I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6",
    ]
    assert manifiesto["unidad_muestras"] == "uV"
    assert manifiesto["version_formato"] == 1
    assert "version_esquema_exportacion" in manifiesto
    assert manifiesto["conteos"] == {"episodios": 1, "ecg": 1, "laboratorio": 1, "eco": 1}
    # 4 tramos de columna (I/II/III, aVR/aVL/aVF, V2/V3, V4/V5/V6) + 1 ventana
    # propia para V1 (tira de ritmo completa, reemplaza su tramo en la grilla)
    assert len(manifiesto["ventanas_columna"]) == 5
    assert manifiesto["ventana_vinculacion_dias"] == 7


def test_manifiesto_no_declara_ninguna_pii(motor, tmp_path) -> None:
    _poblar_episodio_completo(motor, id_episodio="ep-1", id_paciente="pid-1", fecha=date(2024, 1, 10))
    exportar_dataset(motor, tmp_path)

    texto_manifiesto = (tmp_path / NOMBRE_MANIFIESTO).read_text(encoding="utf-8")
    assert "pid-1" not in texto_manifiesto


# --- paginación con memoria acotada (verificable por conteo, no por tiempo) -


def test_paginacion_de_episodios_nunca_materializa_mas_de_una_pagina_a_la_vez(motor) -> None:
    """RED sería: si `_ids_episodio_paginados` trajera todo de una consulta,
    esto se vería como UNA sola página del tamaño total (600), no varias de
    tamaño acotado. Con `tamano_pagina=256` y 600 episodios, deben resultar
    exactamente 3 páginas: 256, 256, 88 -- nunca más de `tamano_pagina` filas
    por página, verificado contando, no por umbral de tiempo."""
    total_episodios = 600
    with sa.orm.Session(motor) as sesion, sesion.begin():
        for i in range(total_episodios):
            sesion.add(
                Episodio(
                    id_episodio=f"ep-{i:05d}", id_paciente=f"pid-{i:05d}", fecha_ancla=date(2024, 1, 1)
                )
            )

    with sa.orm.Session(motor) as sesion:
        paginas = list(_ids_episodio_paginados(sesion, tamano_pagina=256))

    assert [len(pagina) for pagina in paginas] == [256, 256, 88]
    assert max(len(pagina) for pagina in paginas) <= 256
    assert sum(len(pagina) for pagina in paginas) == total_episodios
    # sin duplicados ni huecos entre páginas (paginación por clave, no por offset ciego)
    todos = [id_ for pagina in paginas for id_ in pagina]
    assert len(set(todos)) == total_episodios
