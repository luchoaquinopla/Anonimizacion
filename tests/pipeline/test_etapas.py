"""Tests de `pipeline/etapas.py` -- coherencia con los strings `etapa=` ya usados en PR1-6."""

from __future__ import annotations

from anonimizacion.pipeline.etapas import Etapa


def test_valores_coinciden_con_los_strings_etapa_ya_usados_en_el_codigo() -> None:
    # "extraccion" (extraccion/texto_pymupdf.py), "parseo" (parseo/*.py,
    # registro.py), "pseudonimizacion" (pseudonimizacion/resolutor_claves.py) --
    # ver dominio/errores.py y los módulos que ya lanzan ErrorParseo(etapa=...).
    assert Etapa.INGESTA.value == "ingesta"
    assert Etapa.EXTRACCION.value == "extraccion"
    assert Etapa.DETECCION.value == "deteccion"
    assert Etapa.PARSEO.value == "parseo"
    assert Etapa.RECONCILIACION.value == "reconciliacion"
    assert Etapa.DETECCION_PII.value == "deteccion_pii"
    assert Etapa.PSEUDONIMIZACION.value == "pseudonimizacion"
    assert Etapa.SALIDA.value == "salida"


def test_es_str_enum_comparable_directo_con_el_string_de_etapa() -> None:
    # ErrorDocumento.etapa/ErrorParseo.etapa son `str` planos (dominio/errores.py);
    # Etapa debe poder usarse en su lugar sin conversión explícita.
    assert Etapa.PARSEO == "parseo"
    assert Etapa.PARSEO.value == "parseo"
