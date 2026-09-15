"""Oráculo cuadrático del verificador de PII, sólo para tests (Tarea 4.1).

Copia congelada de la implementación original de
`tests/fixtures/corpus_piloto.py::contar_coincidencias_pii`, antes de
reemplazarla por la versión lineal (`pii/verificador_lineal.py`). No se toca
nunca: es el punto de comparación independiente para el test de equivalencia
(`tests/pii/test_verificador_lineal.py`), no comparte código con la
implementación que audita.
"""

from __future__ import annotations

import random
import string
from collections.abc import Iterable, Sequence


def contar_coincidencias_pii_cuadratico(
    registros: Iterable[object], valores_pii: Sequence[str]
) -> int:
    serializados = tuple(repr(registro).casefold() for registro in registros)
    return sum(valor.casefold() in registro for registro in serializados for valor in valores_pii)


def generar_semilla(
    semilla: int, *, cantidad_registros: int, cantidad_valores: int
) -> tuple[list[str], list[str]]:
    """Corpus sintético determinista con solapamientos y prefijos compartidos.

    Incluye a propósito: valores que son prefijo de otros ("DNI" y "DNI123"),
    valores repetidos con distinta capitalización, un valor vacío y valores
    que nunca aparecen -- casos límite de la semántica a preservar.
    """
    generador = random.Random(semilla)
    alfabeto = string.ascii_letters + string.digits
    base = ["DNI", "DNI123", "DNI1234567", "ana", "ANA", "María", "maria"]
    valores = list(base)
    for _ in range(cantidad_valores - len(base)):
        largo = generador.randint(2, 8)
        valores.append("".join(generador.choices(alfabeto, k=largo)))
    valores.append("")  # el valor vacío cuenta en todos los registros
    generador.shuffle(valores)
    valores = valores[:cantidad_valores] if cantidad_valores else valores

    registros = []
    for _ in range(cantidad_registros):
        piezas = generador.choices(valores + ["ruido", "texto-sin-pii"], k=generador.randint(1, 5))
        registros.append(" ".join(piezas))
    return registros, valores
