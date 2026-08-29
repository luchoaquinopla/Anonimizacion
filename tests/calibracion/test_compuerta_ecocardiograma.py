from __future__ import annotations

from dataclasses import fields

from tests.calibracion.compuerta_ecocardiograma import (
    CONTRATO_ECOCARDIOGRAMA,
    ResumenEcocardiograma,
    comparar_contrato,
    evaluar_ecocardiograma,
)
from tests.fixtures.pdf_sintetico import generar_corpus_clinico


def test_sintetico_cumple_contrato_seguro_derivado_del_original(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=43)
    ruta = next(item.ruta for item in corpus.documentos if item.tipo == "ecocardiograma")

    resumen = evaluar_ecocardiograma(ruta)
    comparacion = comparar_contrato(resumen, CONTRATO_ECOCARDIOGRAMA)

    assert comparacion.cobertura_campos == 1.0
    assert comparacion.equivalencia_medidas
    assert comparacion.equivalencia_secciones
    assert comparacion.equivalencia_procedencia
    assert comparacion.equivalencia_pii
    assert comparacion.equivalencia_estado_final
    assert resumen.estado_final == "aprobado"
    assert resumen.estado_pii == "ejecutada"
    assert resumen.estado_anonimizacion == "ejecutada"
    # Requirement: "Ecocardiograma sin hora emite ausencia, nunca un default"
    # -- aserción negativa: la muestra sintética calibrada NO trae ningún
    # campo de hora; `hora_estudio` debe ser `None` y `precision_hora`
    # `AUSENTE`, nunca `"00:00:00"` ni ninguna otra hora.
    assert resumen.hora_estudio is None
    assert resumen.hora_estudio != "00:00:00"
    assert resumen.precision_hora == "ausente"


def test_resumen_ecocardiograma_no_contiene_valores_identificatorios(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=47)
    ruta = next(item.ruta for item in corpus.documentos if item.tipo == "ecocardiograma")

    serializado = evaluar_ecocardiograma(ruta).como_dict()

    assert set(serializado) == {campo.name for campo in fields(ResumenEcocardiograma)}
    assert serializado["pii_por_categoria"] == {
        "cuasi_identificador": 1,
        "medico": 2,
        "paciente": 2,
        "texto_libre": 0,
    }
    assert serializado["campos_retirados_salida"] == serializado["campos_pii_estructurada"]
