"""Registro inyectable de capturadores de trazos por tipo de documento.

design.md, decisión #1 (`senal-ecg-y-dataset-vinculado`): sólo el ECG trae
trazado vectorial que capturar -- laboratorio y ecocardiograma no lo
necesitan. `extraccion/texto_pymupdf.py` no conoce `TipoDocumento` ni
`detectar_tipo` (evita el ciclo `extraccion -> deteccion -> extraccion`,
porque `deteccion.detector_tipo` ya importa `TextoExtraido`); el ejecutor es
quien cierra el circuito: construye `capturador_para` a partir de este
registro y `detectar_tipo`, y lo inyecta en `extraer_texto_de_flujo`.
"""

from __future__ import annotations

from ..dominio.tipos_documento import TipoDocumento
from .trazos_pymupdf import CapturadorDePagina, capturar_trazos

REGISTRO_CAPTURADORES: dict[TipoDocumento, CapturadorDePagina] = {
    TipoDocumento.ECG: capturar_trazos,
}


def capturador_de(tipo: TipoDocumento) -> CapturadorDePagina | None:
    """`None` si `tipo` no tiene capturador registrado (laboratorio, eco,
    tipo no reconocido)."""
    return REGISTRO_CAPTURADORES.get(tipo)
