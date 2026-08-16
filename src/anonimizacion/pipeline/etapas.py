"""Etapas del pipeline (tasks.md 8.1).

Coherente con los strings `etapa=` ya usados por `ErrorDocumento`/`ErrorParseo`
en fases anteriores (`extraccion/texto_pymupdf.py::_ETAPA = "extraccion"`,
`parseo/*.py::_ETAPA = "parseo"`, `pseudonimizacion/resolutor_claves.py`
llamado con `etapa="pseudonimizacion"`, y `"deteccion"` usado en
`tests/dominio/test_errores.py`). `Etapa` no reemplaza esos módulos -- son
`str` planos por diseño, para no acoplar `dominio/errores.py` a esta capa
más nueva -- pero `pipeline/ejecutor.py` (Fase 8, la única pieza que conoce
la secuencia completa) usa este enum como fuente única de verdad de los
nombres de etapa, en vez de repetir los mismos literales string.

`str, Enum`: comparable directo contra el string plano que ya usan
`ErrorDocumento.etapa`/`ErrorParseo.etapa` (ver `dominio/errores.py`,
mismo patrón que `TipoDocumento`/`CodigoErrorDocumento`).
"""

from __future__ import annotations

from enum import Enum


class Etapa(str, Enum):
    """Las 7 etapas del pipeline (design.md: ingesta -> ... -> emitir)."""

    INGESTA = "ingesta"
    EXTRACCION = "extraccion"
    DETECCION = "deteccion"
    PARSEO = "parseo"
    DETECCION_PII = "deteccion_pii"
    PSEUDONIMIZACION = "pseudonimizacion"
    SALIDA = "salida"
