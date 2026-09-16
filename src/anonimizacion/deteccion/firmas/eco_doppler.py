"""Marcadores del layout de ecocardiograma Doppler.
Verificados contra el texto real; "ECOCARDIOGRAMA DOPPLER"/"FRACCION DE ACORTAMIENTO" se retiraron."""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.ECOCARDIOGRAMA,
    marcadores=(
        "SERVICIO DE ECOCARDIOGRAFIA",
        "ECOGRAFIA DOPPLER COLOR CARDIACA",
        "EVALUACION DE FLUJOS POR DOPPLER",
        "DOPPLER TISULAR",
        "S.C.",
    ),
)
