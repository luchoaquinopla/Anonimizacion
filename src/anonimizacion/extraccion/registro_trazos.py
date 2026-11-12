"""Registro inyectable de capturadores de trazos por tipo de documento.
Sólo el ECG trae trazado vectorial que capturar; el ejecutor inyecta el closure que lo resuelve."""

from __future__ import annotations

from ..dominio.tipos_documento import TipoDocumento
from .trazos_pymupdf import CapturadorDePagina, capturar_trazos

REGISTRO_CAPTURADORES: dict[TipoDocumento, CapturadorDePagina] = {
    TipoDocumento.ECG: capturar_trazos,
}


def capturador_de(tipo: TipoDocumento) -> CapturadorDePagina | None:
    """`None` si `tipo` no tiene capturador registrado (laboratorio, eco, no reconocido)."""
    return REGISTRO_CAPTURADORES.get(tipo)
