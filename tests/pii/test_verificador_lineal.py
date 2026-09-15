"""Equivalencia del verificador lineal (Aho-Corasick) contra el oráculo cuadrático."""

from __future__ import annotations

import pytest

from tests.fixtures.verificador_pii import contar_coincidencias_pii_cuadratico, generar_semilla
from tests.pii.verificador_lineal import contar_coincidencias_pii


@pytest.mark.parametrize(
    "semilla,cantidad_registros,cantidad_valores",
    [
        (1, 20, 12),
        (2, 50, 30),
        (3, 5, 3),
        (7, 200, 60),
    ],
)
def test_equivalencia_contra_oraculo_cuadratico(semilla, cantidad_registros, cantidad_valores):
    registros, valores = generar_semilla(
        semilla, cantidad_registros=cantidad_registros, cantidad_valores=cantidad_valores
    )
    esperado = contar_coincidencias_pii_cuadratico(registros, valores)
    obtenido = contar_coincidencias_pii(registros, valores)
    assert obtenido == esperado


def test_solapamiento_y_prefijos():
    registros = ["contiene DNI123456 en el medio", "sólo dni", "nada relevante aquí"]
    valores = ["DNI", "DNI123", "DNI123456", "DNI1234567890"]
    esperado = contar_coincidencias_pii_cuadratico(registros, valores)
    assert contar_coincidencias_pii(registros, valores) == esperado
    # DNI, DNI123, DNI123456 matchean el primer registro; "DNI" también matchea
    # el segundo ("dni", case-insensitive) -- 4 en total.
    assert esperado == 4


def test_valor_vacio_cuenta_en_todos_los_registros():
    registros = ["a", "b", "c"]
    valores = ["", "a"]
    assert contar_coincidencias_pii(registros, valores) == 4  # "" x3 + "a" x1


def test_multiplicidad_de_valores_repetidos():
    registros = ["contiene ana dos veces: ana"]
    valores = ["ana", "ana", "no-esta"]
    assert contar_coincidencias_pii(registros, valores) == 2  # una presencia, cuenta 2 veces


def test_mayusculas_no_distinguen():
    registros = ["Contiene MARIA en mayúsculas"]
    valores = ["maria"]
    assert contar_coincidencias_pii(registros, valores) == 1


def test_casefold_que_cambia_el_largo_ss_por_eszett():
    # "ß".casefold() == "ss": el patrón crece un carácter respecto del original.
    registros = ["la calle se llama straße en el mapa"]
    valores = ["straße", "strasse"]
    esperado = contar_coincidencias_pii_cuadratico(registros, valores)
    # ambos valores casefoldean a "strasse", que también matchea el texto casefoldeado.
    assert contar_coincidencias_pii(registros, valores) == esperado == 2


def test_casefold_que_cambia_el_largo_ligadura_fi():
    # "ﬁ".casefold() == "fi": el patrón encoge un carácter (ligadura -> dos letras).
    registros = ["trabaja en la ofﬁce central", "trabaja en la office central"]
    valores = ["ofﬁce"]
    esperado = contar_coincidencias_pii_cuadratico(registros, valores)
    assert contar_coincidencias_pii(registros, valores) == esperado == 2


def test_casefold_que_cambia_el_largo_i_turca_con_punto():
    # "İ".casefold() == "i̇" (i + punto combinante U+0307): dos code points.
    registros = ["nació en İstanbul", "nació en istanbul"]
    valores = ["İstanbul"]
    esperado = contar_coincidencias_pii_cuadratico(registros, valores)
    assert contar_coincidencias_pii(registros, valores) == esperado == 1


def test_sin_valores_ni_registros():
    assert contar_coincidencias_pii([], []) == 0
    assert contar_coincidencias_pii(["algo"], []) == 0
    assert contar_coincidencias_pii([], ["algo"]) == 0
