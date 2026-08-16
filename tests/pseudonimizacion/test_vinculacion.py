"""Tests de `vinculacion.py` (spec `patient-pseudonymization`): clustering por ancla ±7 días.

Casos borde obligatorios (design.md, decisión "Ventana de ±7 días -- clustering
por ancla, no encadenado"):

- exactamente 7 días de la ancla -> ENTRA al mismo episodio (`<=`, no `<`).
- exactamente 8 días de la ancla -> NO entra, abre un episodio nuevo (que pasa
  a ser la nueva ancla).
- empates de fecha (mismo día) -> ambos entran, sin ambigüedad.
- SIN encadenado transitivo: si A y B están a 7 días, y B y C están a 7 días,
  pero A y C están a 14 días, C NO debe terminar en el episodio de A (eso es
  la "deriva" que design.md rechaza explícitamente).
"""

from __future__ import annotations

from datetime import date

from anonimizacion.pseudonimizacion.claves import generar_id_episodio
from anonimizacion.pseudonimizacion.vinculacion import DocumentoParaVincular, vincular_episodios

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"


def _doc(id_documento: str, id_paciente: str, fecha: date, tipo: str = "laboratorio") -> DocumentoParaVincular:
    return DocumentoParaVincular(
        id_documento=id_documento, id_paciente=id_paciente, fecha_estudio=fecha, tipo_documento=tipo
    )


def test_exactamente_siete_dias_entra_al_mismo_episodio() -> None:
    documentos = [
        _doc("d1", "pac-1", date(2024, 1, 1)),
        _doc("d2", "pac-1", date(2024, 1, 8)),  # exactamente 7 días de la ancla
    ]

    episodios = vincular_episodios(documentos, PEPPER_TEST)

    assert episodios["d1"] == episodios["d2"]


def test_exactamente_ocho_dias_abre_episodio_nuevo() -> None:
    documentos = [
        _doc("d1", "pac-1", date(2024, 1, 1)),
        _doc("d2", "pac-1", date(2024, 1, 9)),  # exactamente 8 días de la ancla
    ]

    episodios = vincular_episodios(documentos, PEPPER_TEST)

    assert episodios["d1"] != episodios["d2"]


def test_empate_de_fecha_ambos_entran_al_mismo_episodio() -> None:
    documentos = [
        _doc("d1", "pac-1", date(2024, 1, 1), tipo="laboratorio"),
        _doc("d2", "pac-1", date(2024, 1, 1), tipo="ecg"),
    ]

    episodios = vincular_episodios(documentos, PEPPER_TEST)

    assert episodios["d1"] == episodios["d2"]


def test_ancla_no_se_desplaza_dentro_de_la_ventana_evita_deriva() -> None:
    # d1 (ancla=1/1), d2 a +6 dias (7/1, entra, PERO la ancla sigue siendo 1/1,
    # no se recalcula a 7/1), d3 a +12 dias de d1 (13/1) debe quedar FUERA
    # porque 13/1 - 1/1 = 12 > 7, aunque 13/1 - 7/1 = 6 <= 7 (eso sería
    # encadenado transitivo, rechazado explícitamente en design.md)
    documentos = [
        _doc("d1", "pac-1", date(2024, 1, 1)),
        _doc("d2", "pac-1", date(2024, 1, 7)),
        _doc("d3", "pac-1", date(2024, 1, 13)),
    ]

    episodios = vincular_episodios(documentos, PEPPER_TEST)

    assert episodios["d1"] == episodios["d2"]
    assert episodios["d3"] != episodios["d1"]  # NO deriva vía d2


def test_pacientes_distintos_nunca_comparten_episodio() -> None:
    documentos = [
        _doc("d1", "pac-1", date(2024, 1, 1)),
        _doc("d2", "pac-2", date(2024, 1, 1)),
    ]

    episodios = vincular_episodios(documentos, PEPPER_TEST)

    assert episodios["d1"] != episodios["d2"]


def test_id_episodio_coincide_con_generar_id_episodio_de_claves() -> None:
    documentos = [_doc("d1", "pac-1", date(2024, 1, 1))]

    episodios = vincular_episodios(documentos, PEPPER_TEST)

    assert episodios["d1"] == generar_id_episodio(PEPPER_TEST, "pac-1", date(2024, 1, 1))


def test_orden_de_entrada_no_afecta_el_resultado_se_ordena_por_fecha() -> None:
    documentos_en_orden = [
        _doc("d1", "pac-1", date(2024, 1, 1)),
        _doc("d2", "pac-1", date(2024, 1, 8)),
        _doc("d3", "pac-1", date(2024, 1, 20)),
    ]
    documentos_desordenados = [documentos_en_orden[2], documentos_en_orden[0], documentos_en_orden[1]]

    episodios_ordenado = vincular_episodios(documentos_en_orden, PEPPER_TEST)
    episodios_desordenado = vincular_episodios(documentos_desordenados, PEPPER_TEST)

    assert episodios_ordenado == episodios_desordenado


def test_es_determinista_y_recomputable_mismo_lote_mismo_resultado() -> None:
    documentos = [
        _doc("d1", "pac-1", date(2024, 1, 1)),
        _doc("d2", "pac-1", date(2024, 1, 5)),
    ]

    primero = vincular_episodios(documentos, PEPPER_TEST)
    segundo = vincular_episodios(documentos, PEPPER_TEST)

    assert primero == segundo
