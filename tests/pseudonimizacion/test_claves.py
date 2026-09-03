"""Tests de `claves.py` (spec `patient-pseudonymization`): HMAC de claves de identidad.

Pepper de test: valor fijo sintético, jamás leído de infraestructura real.
"""

from __future__ import annotations

import hashlib
import hmac

from anonimizacion.pseudonimizacion.claves import (
    canonicalizar_dni,
    generar_clave_documento,
    generar_id_alt_paciente,
    generar_id_episodio,
    generar_id_matricula_medico,
    generar_id_medico,
    generar_id_paciente,
    normalizar_nombre,
)

SHA256_SINTETICO = "a" * 64
SHA256_SINTETICO_2 = "b" * 64

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


def test_generar_id_alt_paciente_mismo_paciente_distinto_formato_de_nombre_da_misma_clave() -> None:
    # Fix post-merge: mismo paciente (fecha_nac idéntica) escrito distinto en
    # laboratorio ("Apellido , Nombre SegundoNombre") vs ECG ("Apellido Nombre")
    # -- datos 100% inventados, análogos al caso real reportado por el usuario.
    id_lab = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez , Martin Alberto", "1961-09-29")
    id_ecg = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez Martin", "1961-09-29")

    assert id_lab == id_ecg


def test_generar_id_alt_paciente_distinto_segundo_nombre_colisiona_ahora_tradeoff_aceptado() -> None:
    # Trade-off EXPLÍCITO y ACEPTADO con el usuario: dos personas distintas con
    # mismo apellido + mismo primer nombre + misma fecha_nac ahora COLISIONAN
    # (antes no colisionaban porque el segundo nombre completo distinguía).
    # Se documenta acá para que no quede escondido -- es el costo aceptado a
    # cambio de resolver el puente real lab<->ECG.
    id_persona_1 = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez , Martin Alberto", "1961-09-29")
    id_persona_2 = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez , Martin Eduardo", "1961-09-29")

    assert id_persona_1 == id_persona_2


def test_generar_id_alt_paciente_formato_con_coma_y_sin_coma_siguen_siendo_deterministas() -> None:
    id_1 = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez , Martin Alberto", "1961-09-29")
    id_2 = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez , Martin Alberto", "1961-09-29")

    assert id_1 == id_2


def test_generar_id_alt_paciente_nombre_de_una_sola_palabra_no_rompe() -> None:
    # caso borde: nombre sin segundo token (ni apellido separado) -- no debería
    # lanzar excepción, solo producir una clave determinista (aunque poco
    # específica, ya que no hay primer_nombre que extraer).
    id_1 = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez", "1961-09-29")
    id_2 = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez", "1961-09-29")

    assert id_1 == id_2
    assert id_1 != generar_id_alt_paciente(PEPPER_TEST, "Fernandez", "1961-09-29")


def test_generar_id_alt_paciente_nombre_vacio_no_rompe() -> None:
    # caso borde: nombre vacío -- no debería lanzar excepción (aunque el
    # documento real probablemente nunca llega hasta acá con nombre vacío,
    # `IdentidadCruda` no lo prohíbe explícitamente a este nivel).
    id_1 = generar_id_alt_paciente(PEPPER_TEST, "", "1961-09-29")
    id_2 = generar_id_alt_paciente(PEPPER_TEST, "", "1961-09-29")

    assert id_1 == id_2


def test_generar_id_alt_paciente_distinto_apellido_distinta_clave_aunque_mismo_primer_nombre() -> None:
    id_1 = generar_id_alt_paciente(PEPPER_TEST, "Gonzalez , Martin Alberto", "1961-09-29")
    id_2 = generar_id_alt_paciente(PEPPER_TEST, "Fernandez , Martin Alberto", "1961-09-29")

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


def test_generar_id_matricula_medico_es_determinista_y_namespace_propio() -> None:
    # Q3: "la matrícula recibe el mismo tratamiento (es identificador directo)"
    # -- pseudonimizada, en su propio namespace (no mezclada con id_medico
    # del nombre ni con id_paciente).
    id_matricula = generar_id_matricula_medico(PEPPER_TEST, "12345")
    id_matricula_2 = generar_id_matricula_medico(PEPPER_TEST, "12345")
    id_medico_mismo_valor = generar_id_medico(PEPPER_TEST, "12345")

    assert id_matricula == id_matricula_2
    assert id_matricula != id_medico_mismo_valor


def test_generar_id_matricula_medico_distinta_matricula_distinta_clave() -> None:
    id_1 = generar_id_matricula_medico(PEPPER_TEST, "12345")
    id_2 = generar_id_matricula_medico(PEPPER_TEST, "67890")

    assert id_1 != id_2


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


def test_generar_clave_documento_es_estable_entre_corridas() -> None:
    # Requisito 1: "el mismo contenido produce la misma clave en dos corridas"
    clave_1 = generar_clave_documento(PEPPER_TEST, SHA256_SINTETICO)
    clave_2 = generar_clave_documento(PEPPER_TEST, SHA256_SINTETICO)

    assert clave_1 == clave_2


def test_generar_clave_documento_distinto_sha256_distinta_clave() -> None:
    # Requisito 1, segundo escenario: "contenido distinto produce clave distinta"
    clave_1 = generar_clave_documento(PEPPER_TEST, SHA256_SINTETICO)
    clave_2 = generar_clave_documento(PEPPER_TEST, SHA256_SINTETICO_2)

    assert clave_1 != clave_2


def test_generar_clave_documento_namespace_propio_distinto_de_sha256_y_otras_claves() -> None:
    # namespace propio ("documento|"): distinta del sha256 crudo y de las
    # demás claves derivadas del mismo mensaje base.
    clave_documento = generar_clave_documento(PEPPER_TEST, SHA256_SINTETICO)
    id_paciente_mismo_mensaje = generar_id_paciente(PEPPER_TEST, SHA256_SINTETICO)
    id_medico_mismo_mensaje = generar_id_medico(PEPPER_TEST, SHA256_SINTETICO)

    assert clave_documento != SHA256_SINTETICO
    assert clave_documento != id_paciente_mismo_mensaje
    assert clave_documento != id_medico_mismo_mensaje


def test_claves_no_son_reversibles_sin_pepper() -> None:
    # el propio hash no debe poder recuperarse buscando un SHA-256 simple
    # del DNI en claro -- confirma que se usa HMAC (con clave), no hash simple
    hash_simple = hashlib.sha256(b"12345678").hexdigest()[:32]
    id_paciente = generar_id_paciente(PEPPER_TEST, "12345678")

    assert id_paciente != hash_simple
