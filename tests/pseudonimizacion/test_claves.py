"""Tests de `claves.py` (spec `patient-pseudonymization`): HMAC de claves de identidad.

Pepper de test: valor fijo sintético, jamás leído de infraestructura real.
"""

from __future__ import annotations

import hashlib
import hmac

from anonimizacion.pseudonimizacion.claves import (
    canonicalizar_dni,
    generar_id_alt_paciente,
    generar_id_episodio,
    generar_id_medico,
    generar_id_paciente,
    normalizar_nombre,
)

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"


def test_canonicalizar_dni_quita_puntos_y_espacios() -> None:
    assert canonicalizar_dni("12.345.678") == "12345678"
    assert canonicalizar_dni("12 345 678") == "12345678"


def test_canonicalizar_dni_quita_ceros_a_izquierda() -> None:
    assert canonicalizar_dni("00123456") == "123456"


def test_canonicalizar_dni_formas_equivalentes_dan_mismo_resultado() -> None:
    assert canonicalizar_dni("12.345.678") == canonicalizar_dni("12345678")
    assert canonicalizar_dni("012345678") == canonicalizar_dni("12345678")


def test_normalizar_nombre_colapsa_espacios_y_normaliza_mayusculas() -> None:
    assert normalizar_nombre("  Juan   Perez  ") == normalizar_nombre("juan perez")


def test_generar_id_paciente_es_determinista() -> None:
    id_1 = generar_id_paciente(PEPPER_TEST, "12.345.678")
    id_2 = generar_id_paciente(PEPPER_TEST, "12345678")

    assert id_1 == id_2  # canonicalización: mismo DNI, misma clave


def test_generar_id_paciente_distinto_dni_distinta_clave() -> None:
    id_1 = generar_id_paciente(PEPPER_TEST, "12345678")
    id_2 = generar_id_paciente(PEPPER_TEST, "87654321")

    assert id_1 != id_2


def test_generar_id_paciente_distinto_pepper_distinta_clave() -> None:
    id_1 = generar_id_paciente(PEPPER_TEST, "12345678")
    id_2 = generar_id_paciente(b"otro-pepper-de-test", "12345678")

    assert id_1 != id_2


def test_generar_id_paciente_usa_hmac_sha256_con_pepper_como_clave() -> None:
    # el propio HMAC estándar de la stdlib con el mismo mensaje canonicalizado
    # debe reproducir el prefijo de 16 bytes en hex que expone claves.py
    esperado = hmac.new(PEPPER_TEST, b"12345678", hashlib.sha256).digest()[:16].hex()

    assert generar_id_paciente(PEPPER_TEST, "12345678") == esperado


def test_generar_id_alt_paciente_es_determinista_y_usa_nombre_y_fecha() -> None:
    id_1 = generar_id_alt_paciente(PEPPER_TEST, "Juan Perez", "1980-01-01")
    id_2 = generar_id_alt_paciente(PEPPER_TEST, "Juan Perez", "1980-01-01")

    assert id_1 == id_2


def test_generar_id_alt_paciente_distinta_fecha_distinta_clave() -> None:
    id_1 = generar_id_alt_paciente(PEPPER_TEST, "Juan Perez", "1980-01-01")
    id_2 = generar_id_alt_paciente(PEPPER_TEST, "Juan Perez", "1990-05-05")

    assert id_1 != id_2


def test_generar_id_alt_paciente_no_coincide_con_id_paciente_del_mismo_dni() -> None:
    # aunque compartan pepper, son namespaces distintos: nunca deben colisionar
    # por construcción (mensajes con prefijos distintos)
    id_paciente = generar_id_paciente(PEPPER_TEST, "12345678")
    id_alt = generar_id_alt_paciente(PEPPER_TEST, "Juan Perez", "1980-01-01")

    assert id_paciente != id_alt


def test_generar_id_medico_es_determinista_y_namespace_propio() -> None:
    id_medico = generar_id_medico(PEPPER_TEST, "Dr. Roberto Diaz")
    id_medico_2 = generar_id_medico(PEPPER_TEST, "Dr. Roberto Diaz")
    id_paciente_mismo_nombre = generar_id_paciente(PEPPER_TEST, "Dr. Roberto Diaz")

    assert id_medico == id_medico_2
    assert id_medico != id_paciente_mismo_nombre


def test_generar_id_episodio_es_determinista_y_recomputable() -> None:
    from datetime import date

    id_1 = generar_id_episodio(PEPPER_TEST, "abc123", date(2024, 1, 1))
    id_2 = generar_id_episodio(PEPPER_TEST, "abc123", date(2024, 1, 1))

    assert id_1 == id_2


def test_generar_id_episodio_distinta_ancla_distinto_episodio() -> None:
    from datetime import date

    id_1 = generar_id_episodio(PEPPER_TEST, "abc123", date(2024, 1, 1))
    id_2 = generar_id_episodio(PEPPER_TEST, "abc123", date(2024, 1, 15))

    assert id_1 != id_2


def test_claves_no_son_reversibles_sin_pepper() -> None:
    # el propio hash no debe poder recuperarse buscando un SHA-256 simple
    # del DNI en claro -- confirma que se usa HMAC (con clave), no hash simple
    hash_simple = hashlib.sha256(b"12345678").hexdigest()[:32]
    id_paciente = generar_id_paciente(PEPPER_TEST, "12345678")

    assert id_paciente != hash_simple
