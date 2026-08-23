import json
from collections import Counter

import pytest

from tests.carga.ejecutar_corpus import (
    DUPLICADOS_CARGA_1000,
    ORACULO_CARGA_1000,
    PLAN_CARGA_1000,
    OraculoCarga,
    ejecutar_carga,
    ejecutar_cli,
    guardar_reporte,
)


def test_plan_carga_tiene_exactamente_mil_pdfs_con_mezcla_controlada() -> None:
    casos = Counter(PLAN_CARGA_1000)

    assert casos == {
        "completo": 320,
        "limite_7": 4,
        "separacion_8": 3,
        "faltante": 3,
        "ambiguo": 2,
        "corrupto": 1,
    }
    assert sum({"completo": 3, "limite_7": 3, "separacion_8": 3, "faltante": 2, "ambiguo": 4, "corrupto": 3}[tipo] * cantidad for tipo, cantidad in casos.items()) + DUPLICADOS_CARGA_1000 == 1_000


def test_runner_mide_pipeline_real_y_deduplicacion(tmp_path) -> None:
    oraculo = OraculoCarga(6, 5, 1, 1, 3, {"cobertura_incompleta": 2}, 0, 0)
    resultado = ejecutar_carga(
        tmp_path,
        semilla=20260823,
        tipos_caso=("completo", "faltante"),
        duplicados=1,
        oraculo=oraculo,
    )

    assert resultado.pdfs_generados == 6
    assert resultado.documentos_unicos == 5
    assert resultado.duplicados_omitidos == 1
    assert resultado.documentos_aprobados == 3
    assert resultado.documentos_en_cuarentena == 2
    assert resultado.episodios_aprobados == 1
    assert resultado.cuarentenas_esperadas == 2
    assert resultado.fallos_inesperados == 0
    assert resultado.reintentos == 0
    assert resultado.tiempo_total_segundos > 0
    assert resultado.throughput_archivos_fisicos_segundo > 0
    assert resultado.throughput_documentos_unicos_segundo > 0
    assert resultado.memoria_pico_lifetime_proceso_bytes > 0
    assert resultado.pii_en_salida == 0
    assert resultado.oraculo_validado

    ruta_reporte = tmp_path / "reporte_seguro.json"
    guardar_reporte(resultado, ruta_reporte)
    reporte = ruta_reporte.read_text(encoding="utf-8").casefold()
    assert "paciente sintetico" not in reporte
    assert "profesional sintetico" not in reporte
    assert '"pdfs_generados": 6' in reporte


def test_cli_es_reejecutable_y_agrega_reportes_sin_contaminar_corridas(tmp_path) -> None:
    oraculo = OraculoCarga(3, 3, 0, 1, 3, {}, 0, 0)
    (tmp_path / "reporte_seguro.json").write_text(
        json.dumps({"pdfs_generados": 3, "fallos": 0}), encoding="utf-8"
    )

    ejecutar_cli(tmp_path, semilla=7, tipos_caso=("completo",), duplicados=0, oraculo=oraculo)
    ejecutar_cli(tmp_path, semilla=7, tipos_caso=("completo",), duplicados=0, oraculo=oraculo)

    corridas = list((tmp_path / "corridas").iterdir())
    reporte = json.loads((tmp_path / "reporte_seguro.json").read_text(encoding="utf-8"))
    assert len(corridas) == 2
    assert len(reporte["corridas"]) == 2
    assert reporte["ultima_corrida"]["documentos_aprobados"] == 3


def test_oraculo_1k_declara_estados_y_codigos_completos() -> None:
    assert ORACULO_CARGA_1000.documentos_aprobados == 972
    assert ORACULO_CARGA_1000.cuarentena_por_codigo == {
        "cobertura_ambigua": 8,
        "cobertura_incompleta": 17,
        "parseo_incompleto": 1,
    }


def test_runner_rechaza_desvio_del_oraculo(tmp_path) -> None:
    oraculo_incorrecto = OraculoCarga(3, 3, 0, 1, 2, {}, 0, 0)

    with pytest.raises(AssertionError, match="oraculo de carga"):
        ejecutar_carga(
            tmp_path,
            semilla=9,
            tipos_caso=("completo",),
            duplicados=0,
            oraculo=oraculo_incorrecto,
        )
