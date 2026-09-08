"""Tests del reconocedor custom de DNI argentino (Presidio `PatternRecognizer`)."""

from __future__ import annotations

from anonimizacion.pii.reconocedores.dni_ar import ENTIDAD_DNI_AR, ReconocedorDniAr


def _reconocedor() -> ReconocedorDniAr:
    return ReconocedorDniAr()


def test_reconoce_dni_con_puntos_como_separador_de_miles() -> None:
    resultados = _reconocedor().analyze(
        "El paciente con DNI 12.345.678 fue atendido.", entities=[ENTIDAD_DNI_AR]
    )
    assert any(r.entity_type == ENTIDAD_DNI_AR for r in resultados)


def test_reconoce_dni_sin_puntos() -> None:
    resultados = _reconocedor().analyze(
        "El paciente con DNI 12345678 fue atendido.", entities=[ENTIDAD_DNI_AR]
    )
    assert any(r.entity_type == ENTIDAD_DNI_AR for r in resultados)


def test_reconoce_dni_de_siete_digitos() -> None:
    resultados = _reconocedor().analyze("DNI 4.123.456", entities=[ENTIDAD_DNI_AR])
    assert any(r.entity_type == ENTIDAD_DNI_AR for r in resultados)


def test_reconoce_dni_de_seis_digitos_sin_puntos() -> None:
    # DNI viejo real: personas de edad avanzada (mayoría en cardiología)
    # pueden tener DNI de 6 cifras, sin cero a la izquierda (ver
    # `dni_ar.py`, docstring de `_DNI_MINIMO`).
    resultados = _reconocedor().analyze("DNI 987654", entities=[ENTIDAD_DNI_AR])
    assert any(r.entity_type == ENTIDAD_DNI_AR for r in resultados)


def test_reconoce_dni_de_seis_digitos_con_puntos() -> None:
    # Mismo DNI viejo, agrupado con puntos de a tres desde la derecha
    # ("987.654"), igual que se agrupan los de 7-8 dígitos.
    resultados = _reconocedor().analyze("DNI 987.654", entities=[ENTIDAD_DNI_AR])
    assert any(r.entity_type == ENTIDAD_DNI_AR for r in resultados)


def test_rechaza_numero_de_cinco_digitos() -> None:
    # 5 dígitos: por debajo del piso real de DNI (6 dígitos, ver
    # `_DNI_MINIMO`) -- sigue fuera de rango tras la Tarea 3.
    resultados = _reconocedor().analyze("Código interno 12345", entities=[ENTIDAD_DNI_AR])
    assert resultados == []


def test_rechaza_numero_de_muchos_digitos() -> None:
    # 10 dígitos: no es un DNI, podría ser un teléfono u otro identificador
    resultados = _reconocedor().analyze("Referencia 1234567890", entities=[ENTIDAD_DNI_AR])
    assert resultados == []


def test_dni_con_puntos_mal_agrupados_es_rechazado() -> None:
    # Agrupación de puntos inválida para un DNI (no son grupos de miles reales)
    resultados = _reconocedor().analyze("Nro 1.2.345.678", entities=[ENTIDAD_DNI_AR])
    assert resultados == []
