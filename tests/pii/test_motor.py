"""Tests del motor de detección de PII (Presidio + spaCy es_core_news_lg + regex DNI).

Nota: instancia el motor real (carga el modelo spaCy) — es intencionalmente
lento en esta suite (spec `pii-detection`: "100% offline", nada de red; la
lentitud es costo de carga del modelo, no de red). `conftest.py` ya agrega
`src/` al path; el modelo se carga una sola vez por módulo vía fixture con
scope de módulo para no pagar el costo de carga en cada test.
"""

from __future__ import annotations

import pytest

from anonimizacion.pii.motor import MotorPii


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


def test_detecta_nombre_de_persona_via_ner_spacy(motor: MotorPii) -> None:
    detecciones = motor.detectar("El paciente Juan Perez fue atendido ayer.")
    assert any(d.tipo_entidad == "PERSON" for d in detecciones)


def test_detecta_dni_via_reconocedor_custom(motor: MotorPii) -> None:
    detecciones = motor.detectar("DNI del paciente: 12.345.678.")
    assert any(d.tipo_entidad == "DNI_AR" for d in detecciones)


def test_deteccion_de_alta_confianza_no_se_marca_baja_confianza(motor: MotorPii) -> None:
    detecciones = motor.detectar("DNI del paciente: 12.345.678.")
    (dni,) = [d for d in detecciones if d.tipo_entidad == "DNI_AR"]
    assert dni.baja_confianza is False


def test_deteccion_de_bajo_puntaje_se_marca_como_baja_confianza(motor: MotorPii) -> None:
    # DNI sin puntos: score bajo (0.5) por ambigüedad con otros números de 7-8 dígitos.
    detecciones = motor.detectar("Numero 12345678 en el documento.")
    (dni,) = [d for d in detecciones if d.tipo_entidad == "DNI_AR"]
    assert dni.baja_confianza is True


def test_deteccion_de_baja_confianza_no_se_descarta(motor: MotorPii) -> None:
    # Falso negativo es peor que falso positivo: se marca, no se elimina.
    detecciones = motor.detectar("Numero 12345678 en el documento.")
    assert any(d.tipo_entidad == "DNI_AR" for d in detecciones)


def test_ids_internos_se_evaluan_como_cuasi_identificadores(motor: MotorPii) -> None:
    detecciones = motor.evaluar_ids_internos(("PET-000123", "EST-000456"))
    assert len(detecciones) == 2
    assert all(d.tipo_entidad == "ID_INTERNO" for d in detecciones)
    assert all(d.cuasi_identificador is True for d in detecciones)


def test_ids_internos_no_se_marcan_como_baja_confianza(motor: MotorPii) -> None:
    # Son campos ya conocidos (vienen de IdentidadCruda.ids_internos, no de NER/regex
    # incierto): no hay ambigüedad de detección, así que no aplica el flag.
    (deteccion,) = motor.evaluar_ids_internos(("PET-000123",))
    assert deteccion.baja_confianza is False


def test_deteccion_normal_no_es_cuasi_identificador_por_defecto(motor: MotorPii) -> None:
    detecciones = motor.detectar("DNI del paciente: 12.345.678.")
    (dni,) = [d for d in detecciones if d.tipo_entidad == "DNI_AR"]
    assert dni.cuasi_identificador is False
