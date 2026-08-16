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


def test_rechaza_numero_fuera_de_rango_de_dni() -> None:
    # 6 dígitos: fuera del rango típico de DNI argentino (7-8 dígitos)
    resultados = _reconocedor().analyze("Código interno 123456", entities=[ENTIDAD_DNI_AR])
    assert resultados == []


def test_rechaza_numero_de_muchos_digitos() -> None:
    # 10 dígitos: no es un DNI, podría ser un teléfono u otro identificador
    resultados = _reconocedor().analyze("Referencia 1234567890", entities=[ENTIDAD_DNI_AR])
    assert resultados == []


def test_dni_con_puntos_mal_agrupados_es_rechazado() -> None:
    # Agrupación de puntos inválida para un DNI (no son grupos de miles reales)
    resultados = _reconocedor().analyze("Nro 1.2.345.678", entities=[ENTIDAD_DNI_AR])
    assert resultados == []
