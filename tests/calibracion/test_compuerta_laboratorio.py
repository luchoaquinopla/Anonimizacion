from __future__ import annotations

from dataclasses import fields

from tests.calibracion.compuerta_laboratorio import (
    CONTRATO_LABORATORIO,
    ResumenLaboratorio,
    comparar_contrato,
    evaluar_laboratorio,
)
from tests.fixtures.pdf_sintetico import generar_corpus_clinico


def test_sintetico_cumple_contrato_seguro_derivado_del_original(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=31)
    ruta = next(documento.ruta for documento in corpus.documentos if documento.tipo == "laboratorio")

    resumen = evaluar_laboratorio(ruta)
    comparacion = comparar_contrato(resumen, CONTRATO_LABORATORIO)

    assert comparacion.cobertura_campos == 1.0
    assert comparacion.cobertura_secciones == 1.0
    assert comparacion.cobertura_determinaciones == 1.0
    assert comparacion.equivalencia_tipos
    assert comparacion.equivalencia_pii
    assert comparacion.equivalencia_estado_final
    assert resumen.estado_parseo == "aprobado"
    assert resumen.estado_final == "cuarentena"
    assert resumen.codigo_final == "cobertura_incompleta"
    assert resumen.etapa_final == "reconciliacion"


def test_resumen_de_calibracion_no_contiene_valores_identificatorios(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=37)
    ruta = next(documento.ruta for documento in corpus.documentos if documento.tipo == "laboratorio")

    resumen = evaluar_laboratorio(ruta)
    serializado = resumen.como_dict()

    assert set(serializado) == {campo.name for campo in fields(ResumenLaboratorio)}
    assert serializado["campos_pii_estructurada"] == [
        "identidad.dni",
        "identidad.fecha_nac",
        "identidad.ids_internos",
        "identidad.nombre",
        "adicionales.medico_derivante",
    ]
    assert serializado["estado_pii"] == "no_ejecutada_por_cuarentena"
    assert serializado["pii_por_categoria"] == {}
    assert serializado["estado_anonimizacion"] == "no_ejecutada_por_cuarentena"
    assert serializado["campos_retirados_salida"] == []
