"""Pruebas RED de contrato para el adaptador de laboratorio en memoria con entradas sintéticas."""

from importlib import import_module

AdaptadorFamiliaLaboratorio = import_module(
    "ingesta_clinica.adaptadores.salida.laboratorio"
).AdaptadorFamiliaLaboratorio


def test_adaptador_de_laboratorio_clasifica_contenido_sintetico_de_laboratorio() -> (
    None
):
    adaptador = AdaptadorFamiliaLaboratorio()

    resultado = adaptador.extraer(b"INFORME_LABORATORIO marcador_alfa")

    assert resultado.es_laboratorio is True


def test_adaptador_de_laboratorio_rechaza_un_documento_no_laboratorio_de_forma_segura() -> (
    None
):
    adaptador = AdaptadorFamiliaLaboratorio()

    resultado = adaptador.extraer(b"DOCUMENTO_NO_COMPATIBLE sintetico")

    assert resultado.es_laboratorio is False
    assert resultado.codigo_rechazo == "FAMILIA_DOCUMENTO_NO_COMPATIBLE"


def test_procedencia_efimera_contiene_solo_metadatos_tecnicos_de_ubicacion() -> None:
    adaptador = AdaptadorFamiliaLaboratorio()

    resultado = adaptador.extraer(b"INFORME_LABORATORIO marcador_alfa")

    assert resultado.procedencia is not None
    assert set(resultado.procedencia) == {"numero_pagina", "indice_bloque"}
    assert all(isinstance(valor, int) for valor in resultado.procedencia.values())
    assert "INFORME_LABORATORIO" not in repr(resultado.procedencia)
