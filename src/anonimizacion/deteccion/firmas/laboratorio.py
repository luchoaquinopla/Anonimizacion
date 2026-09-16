"""Marcadores del layout de laboratorio general.
"QUIMICA CLINICA" (sin tilde) no aparece en el real ("QUÍMICA CLÍNICA"); la detección no normaliza acentos."""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.LABORATORIO,
    marcadores=("HEMATOLOGIA", "HEMOSTASIA", "QUIMICA CLINICA", "QUÍMICA CLÍNICA", "IONOGRAMA"),
)
