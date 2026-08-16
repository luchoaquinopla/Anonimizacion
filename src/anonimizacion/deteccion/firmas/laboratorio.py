"""Marcadores del layout de laboratorio general."""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.LABORATORIO,
    marcadores=("HEMATOLOGIA", "HEMOSTASIA", "QUIMICA CLINICA", "IONOGRAMA"),
)
