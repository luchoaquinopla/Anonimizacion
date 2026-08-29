from __future__ import annotations

from dataclasses import fields, replace
from datetime import time

import pytest

from anonimizacion.dominio.precision_hora import PrecisionHora
from tests.calibracion.compuerta_ecg import (
    CONTRATO_ECG,
    ResumenEcg,
    comparar_contrato,
    evaluar_ecg,
)
from tests.fixtures.pdf_sintetico import generar_corpus_clinico


@pytest.mark.parametrize("semilla", (53, 59))
def test_sintetico_cumple_contrato_seguro_derivado_del_original(tmp_path, semilla: int) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=semilla)
    ruta = next(item.ruta for item in corpus.documentos if item.tipo == "ecg")

    resumen = evaluar_ecg(ruta)
    comparacion = comparar_contrato(resumen, CONTRATO_ECG)

    assert comparacion.cobertura_campos == 1.0
    assert comparacion.equivalencia_metricas
    assert comparacion.equivalencia_procedencia
    assert comparacion.equivalencia_advertencia
    assert comparacion.equivalencia_pii
    assert comparacion.equivalencia_estado_final
    assert resumen.estado_final == "aprobado"
    assert resumen.estado_pii == "ejecutada"
    assert resumen.estado_anonimizacion == "ejecutada"
    # Requirement: "ECG conserva la hora capturada en el header" -- la muestra
    # sintética calibrada trae `08:30:00` (ver `tests/fixtures/pdf_sintetico.py`,
    # `_crear_ecg`); la compuerta verifica el valor exacto campo por campo.
    assert resumen.hora_estudio == time(8, 30, 0).isoformat()
    assert resumen.precision_hora == PrecisionHora.SEGUNDO.value


def test_resumen_ecg_no_contiene_valores_identificatorios_ni_senal(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=59)
    ruta = next(item.ruta for item in corpus.documentos if item.tipo == "ecg")

    serializado = evaluar_ecg(ruta).como_dict()

    assert set(serializado) == {campo.name for campo in fields(ResumenEcg)}
    assert serializado["imagen_trazado"] == "fuera_de_contrato_clinico"
    assert serializado["campos_retirados_salida"] == serializado["campos_pii_estructurada"]


def test_comparacion_rechaza_cabecera_incompleta() -> None:
    incompleto = replace(CONTRATO_ECG, campos_identidad=("nombre",))

    assert comparar_contrato(incompleto, CONTRATO_ECG).cobertura_campos < 1.0
