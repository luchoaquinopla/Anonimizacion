import json
from collections import Counter

import pytest

from tests.carga.ejecutar_corpus import (
    DUPLICADOS_CARGA_10000,
    DUPLICADOS_CARGA_1000,
    ORACULO_CARGA_10000,
    ORACULO_CARGA_1000,
    PLAN_CARGA_10000,
    PLAN_CARGA_1000,
    VERSION_MEDICION,
    OraculoCarga,
    ejecutar_carga,
    ejecutar_cli,
    evaluar_preflight,
    guardar_reporte,
    migrar_reporte_legacy,
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
    oraculo = OraculoCarga(6, 6, 5, 1, 1, 3, {"episodio_incompleto": 2}, 0, 0)
    resultado = ejecutar_carga(
        tmp_path,
        semilla=20260823,
        tipos_caso=("completo", "faltante"),
        duplicados=1,
        oraculo=oraculo,
    )

    assert resultado.pdfs_entrada == 6
    assert resultado.pdfs_staging_generados == 6
    assert resultado.documentos_unicos == 5
    assert resultado.duplicados_omitidos == 1
    assert resultado.documentos_aprobados == 3
    assert resultado.documentos_en_cuarentena == 2
    assert resultado.episodios_aprobados == 1
    assert resultado.cuarentenas_esperadas == 2
    assert resultado.fallos_inesperados == 0
    assert resultado.reintentos == 0
    assert resultado.tiempo_preparacion_segundos > 0
    assert resultado.tiempo_procesamiento_segundos > 0
    assert resultado.tiempo_verificacion_segundos >= 0
    assert resultado.throughput_procesamiento_pdfs_entrada_segundo > 0
    assert resultado.throughput_procesamiento_documentos_unicos_segundo > 0
    assert resultado.memoria_pico_lifetime_proceso_bytes > 0
    assert resultado.pii_en_salida == 0
    assert resultado.oraculo_validado
    assert resultado.version_medicion == "fases-separadas-v1"

    ruta_reporte = tmp_path / "reporte_seguro.json"
    guardar_reporte(resultado, ruta_reporte)
    reporte = ruta_reporte.read_text(encoding="utf-8").casefold()
    assert "paciente sintetico" not in reporte
    assert "profesional sintetico" not in reporte
    assert '"pdfs_entrada": 6' in reporte
    assert '"pdfs_staging_generados": 6' in reporte
    assert "pdfs_generados" not in reporte
    assert "throughput_archivos_fisicos" not in reporte


def test_corrida_nueva_no_comparte_clave_de_throughput_con_metodologia_vieja(
    tmp_path,
) -> None:
    """Centinela del hallazgo bloqueante: un reporte de la metodologia vieja
    (reloj total, sin `version_medicion`) ya existe en disco. Si la corrida
    nueva escribiera su throughput bajo la MISMA clave, alguien que grafique
    esa serie leeria un salto de ~4.5 a ~36 pdfs/s como "mejoramos el
    throughput 8x" cuando lo unico que cambio fue que se dejo de cronometrar.
    Las claves de throughput de ambas corridas no deben solaparse: asi la
    colision es imposible por construccion, no por que alguien recuerde
    filtrar.
    """
    ruta = tmp_path / "reporte_seguro.json"
    corrida_metodologia_vieja = {
        "pdfs_entrada": 1_000,
        "throughput_pdfs_entrada_segundo": 4.561,
        "oraculo_validado": True,
    }
    ruta.write_text(
        json.dumps({"corridas": [corrida_metodologia_vieja]}), encoding="utf-8"
    )

    oraculo = OraculoCarga(3, 3, 3, 0, 1, 3, {}, 0, 0)
    resultado = ejecutar_carga(
        tmp_path / "corrida-nueva",
        semilla=7,
        tipos_caso=("completo",),
        duplicados=0,
        oraculo=oraculo,
    )
    guardar_reporte(resultado, ruta)

    reporte = json.loads(ruta.read_text(encoding="utf-8"))
    claves_throughput_vieja = {
        clave for clave in corrida_metodologia_vieja if clave.startswith("throughput_")
    }
    claves_throughput_nueva = {
        clave for clave in resultado.como_dict() if clave.startswith("throughput_")
    }

    assert claves_throughput_vieja.isdisjoint(claves_throughput_nueva)
    assert reporte["corridas"][0] == corrida_metodologia_vieja
    assert reporte["corridas"][-1]["version_medicion"] == VERSION_MEDICION


def test_cli_es_reejecutable_y_agrega_reportes_sin_contaminar_corridas(tmp_path) -> None:
    oraculo = OraculoCarga(3, 3, 3, 0, 1, 3, {}, 0, 0)
    (tmp_path / "reporte_seguro.json").write_text(
        json.dumps({
            "corridas": [{
                "pdfs_generados": 3,
                "throughput_archivos_fisicos_segundo": 1.5,
                "oraculo_validado": True,
            }]
        }),
        encoding="utf-8",
    )

    ejecutar_cli(tmp_path, semilla=7, tipos_caso=("completo",), duplicados=0, oraculo=oraculo)
    ejecutar_cli(tmp_path, semilla=7, tipos_caso=("completo",), duplicados=0, oraculo=oraculo)

    corridas = list((tmp_path / "corridas").iterdir())
    reporte = json.loads((tmp_path / "reporte_seguro.json").read_text(encoding="utf-8"))
    assert len(corridas) == 2
    assert len(reporte["corridas"]) == 3
    assert reporte["ultima_corrida"]["documentos_aprobados"] == 3
    assert reporte["preflight"]["aprobado"] is True
    assert reporte["preflight"]["espacio_disponible_inicial_bytes"] > 0
    assert reporte["preflight"]["memoria_disponible_inicial_bytes"] > 0
    assert reporte["preflight"]["disco_estimado_bytes"] > 0
    assert reporte["preflight"]["tiempo_estimado_segundos"] > 0
    assert all("pdfs_generados" not in corrida for corrida in reporte["corridas"])
    assert reporte["corridas"][0]["pdfs_entrada"] == 3
    assert reporte["corridas"][0]["pdfs_staging_generados"] == 3


def test_oraculo_1k_declara_estados_y_codigos_completos() -> None:
    assert ORACULO_CARGA_1000.documentos_aprobados == 972
    assert ORACULO_CARGA_1000.cuarentena_por_codigo == {
        "episodio_ambiguo": 8,
        "episodio_incompleto": 17,
        "parseo_incompleto": 1,
    }


def test_perfil_10k_escala_la_mezcla_y_el_oraculo_sin_duplicar_logica() -> None:
    casos = Counter(PLAN_CARGA_10000)
    documentos_por_caso = {
        "completo": 3,
        "limite_7": 3,
        "separacion_8": 3,
        "faltante": 2,
        "ambiguo": 4,
        "corrupto": 3,
    }

    assert casos == {
        "completo": 3_200,
        "limite_7": 40,
        "separacion_8": 30,
        "faltante": 30,
        "ambiguo": 20,
        "corrupto": 10,
    }
    total_entrada = sum(
        documentos_por_caso[tipo] * cantidad for tipo, cantidad in casos.items()
    ) + DUPLICADOS_CARGA_10000
    assert total_entrada == 10_000
    assert ORACULO_CARGA_10000 == OraculoCarga(
        10_000,
        10_050,
        9_980,
        20,
        3_240,
        9_720,
        {"episodio_ambiguo": 80, "episodio_incompleto": 170, "parseo_incompleto": 10},
        0,
        0,
    )
    assert DUPLICADOS_CARGA_10000 == 20


def test_runner_rechaza_desvio_del_oraculo(tmp_path) -> None:
    oraculo_incorrecto = OraculoCarga(3, 3, 3, 0, 1, 2, {}, 0, 0)

    with pytest.raises(AssertionError, match="oraculo de carga"):
        ejecutar_carga(
            tmp_path,
            semilla=9,
            tipos_caso=("completo",),
            duplicados=0,
            oraculo=oraculo_incorrecto,
        )


def test_migracion_reporte_legacy_es_atomica_y_conserva_historial(tmp_path) -> None:
    ruta = tmp_path / "reporte_seguro.json"
    legado = {
        "pdfs_generados": 1_000,
        "throughput_archivos_fisicos_segundo": 4.414,
        "oraculo_validado": True,
    }
    ruta.write_text(
        json.dumps({"ultima_corrida": legado, "corridas": [legado]}), encoding="utf-8"
    )

    esperado = evaluar_preflight(tmp_path, ORACULO_CARGA_10000)
    migrar_reporte_legacy(ruta, oraculo=ORACULO_CARGA_10000)

    reporte = json.loads(ruta.read_text(encoding="utf-8"))
    assert reporte["ultima_corrida"]["pdfs_entrada"] == 1_000
    assert reporte["ultima_corrida"]["pdfs_staging_generados"] == 1_005
    assert reporte["corridas"][0]["throughput_pdfs_entrada_segundo"] == 4.414
    assert reporte["preflight"]["disco_estimado_bytes"] == esperado.disco_estimado_bytes
    assert not ruta.with_suffix(".tmp").exists()
