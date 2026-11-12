"""Fuente única de verdad de los nombres de etapa (`str, Enum`, comparable contra el string
plano de `ErrorDocumento.etapa`/`ErrorParseo.etapa`); no reemplaza esos módulos, que siguen en `str`."""

from __future__ import annotations

from enum import Enum


class Etapa(str, Enum):
    """Vocabulario unificado de etapas (10 miembros). `EtapaDocumento` (`dominio/errores.py`)
    no cambia de forma; este enum es la fuente de verdad de los NOMBRES, no del tipo."""

    INGESTA = "ingesta"
    DESPACHO = "despacho"  # proceso hijo muerto antes de EXTRACCION, ver EtapaDocumento.DESPACHO
    EXTRACCION = "extraccion"
    DETECCION = "deteccion"
    PARSEO = "parseo"
    RECONCILIACION = "reconciliacion"
    COORDINACION = "coordinacion"  # nivel episodio, no documento: no confundir con fallo de campo
    DETECCION_PII = "deteccion_pii"
    PSEUDONIMIZACION = "pseudonimizacion"
    SALIDA = "salida"
