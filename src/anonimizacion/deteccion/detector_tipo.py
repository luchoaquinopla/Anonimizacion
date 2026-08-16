"""`detectar_tipo`: clasifica un `TextoExtraido` según las firmas conocidas.

Spec `document-type-detection`: nunca lanza — si ninguna firma coincide,
devuelve `TIPO_NO_RECONOCIDO`. Esa decisión es intencional: el pipeline no
debe abortar el lote por un layout desconocido, el documento sigue su camino
hacia cuarentena en una etapa posterior, no acá.
"""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

from .firmas import FIRMAS


def detectar_tipo(texto: TextoExtraido) -> TipoDocumento:
    texto_normalizado = texto.texto_completo.upper()
    for firma in FIRMAS:
        if firma.coincide(texto_normalizado):
            return firma.tipo
    return TipoDocumento.TIPO_NO_RECONOCIDO
