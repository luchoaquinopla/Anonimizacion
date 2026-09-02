from __future__ import annotations

from dataclasses import fields
from datetime import time

from anonimizacion.dominio.precision_hora import PrecisionHora
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
    assert resumen.secciones == CONTRATO_LABORATORIO.secciones
    assert resumen.determinaciones == CONTRATO_LABORATORIO.determinaciones
    assert comparacion.equivalencia_tipos
    assert comparacion.equivalencia_pii
    assert comparacion.equivalencia_estado_final
    assert resumen.estado_parseo == "aprobado"
    assert resumen.estado_final == "aprobado"
    assert resumen.codigo_final is None
    assert resumen.etapa_final is None
    assert resumen.estado_pii == "ejecutada"
    assert resumen.estado_anonimizacion == "ejecutada"
    # Requirement: "Laboratorio expone la hora de extracción como campo
    # tipado" -- la muestra sintética calibrada trae `Hora de Extraccion: 08:30`
    # (ver `tests/fixtures/pdf_sintetico.py`, `_encabezado_laboratorio`); la
    # compuerta verifica el valor exacto y que ya no viva en adicionales.
    assert resumen.hora_estudio == time(8, 30).isoformat()
    assert resumen.precision_hora == PrecisionHora.MINUTO.value
    assert "hora_extraccion" not in resumen.campos_adicionales


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
    assert serializado["estado_pii"] == "ejecutada"
    assert serializado["pii_por_categoria"] == {
        "cuasi_identificador": 1,
        "medico": 1,
        "paciente": 3,
        "texto_libre": 0,
    }
    assert serializado["estado_anonimizacion"] == "ejecutada"
    assert serializado["campos_retirados_salida"] == serializado["campos_pii_estructurada"]
