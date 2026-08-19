"""Pruebas de normalizadores explícitos de reconciliación."""

from __future__ import annotations

import pytest

from anonimizacion.reconciliacion.normalizacion import (
    normalizar_fecha_iso,
    normalizar_numero,
    normalizar_texto,
)
from anonimizacion.reconciliacion.base import ReferenciaCampo


@pytest.mark.parametrize(
    ("original", "esperado"),
    [
        ("  Ritmo   sinusal ", "ritmo sinusal"),
        ("RITMO SINUSAL", "ritmo sinusal"),
    ],
)
def test_normalizar_texto_iguala_espacios_y_mayusculas(original: str, esperado: str) -> None:
    assert normalizar_texto(original) == esperado


@pytest.mark.parametrize(
    ("original", "esperado"),
    [("12,50", "12.50"), (" 12.50 ", "12.50")],
)
def test_normalizar_numero_acepta_coma_o_punto_decimal(original: str, esperado: str) -> None:
    assert normalizar_numero(original) == esperado


@pytest.mark.parametrize(
    ("original", "esperado"),
    [("15/01/2024", "2024-01-15"), ("2024-01-15", "2024-01-15")],
)
def test_normalizar_fecha_iso_convierte_solo_formatos_permitidos(
    original: str, esperado: str
) -> None:
    assert normalizar_fecha_iso(original) == esperado


@pytest.mark.parametrize(
    ("original", "decimales_permitidos"),
    [("12 mg/dL", None), ("-12", None), ("12.500", 2)],
)
def test_normalizadores_no_aceptan_cambios_semanticos(
    original: str, decimales_permitidos: int | None
) -> None:
    with pytest.raises(ValueError):
        normalizar_numero(original, decimales_permitidos=decimales_permitidos)


@pytest.mark.parametrize("atributo", ["valor", "texto", "huella", "dni"])
def test_referencia_no_expone_campos_persistibles_sensibles(atributo: str) -> None:
    referencia = ReferenciaCampo(id_campo="ecg.vent_rate", pagina=1, selector="ecg.vent_rate")
    assert atributo not in vars(referencia)


@pytest.mark.parametrize("identificador", ["nombre del paciente", "campo@valor"])
def test_referencia_rechaza_selectores_que_pueden_transportar_texto(
    identificador: str,
) -> None:
    with pytest.raises(ValueError):
        ReferenciaCampo(id_campo=identificador, pagina=1, selector="ecg.frecuencia")


@pytest.mark.parametrize(
    ("id_campo", "selector"),
    [
        ("ecg.valor-4a75616e", "ecg.vent_rate"),
        ("ecg.vent_rate", "texto.valor_clinico"),
    ],
)
def test_referencia_rechaza_identificadores_fuera_de_la_whitelist(
    id_campo: str, selector: str
) -> None:
    with pytest.raises(ValueError):
        ReferenciaCampo(id_campo=id_campo, pagina=1, selector=selector)
