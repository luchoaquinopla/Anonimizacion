"""Marcadores del layout de ECG Mortara."""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.ECG,
    marcadores=("MORTARA", "VENT RATE", "PR-QRS-QT/QTC"),
)
