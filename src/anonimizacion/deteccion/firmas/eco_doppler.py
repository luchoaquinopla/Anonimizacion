"""Marcadores del layout de ecocardiograma Doppler."""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.ECOCARDIOGRAMA,
    marcadores=("ECOCARDIOGRAMA DOPPLER", "FRACCION DE ACORTAMIENTO", "S.C."),
)
