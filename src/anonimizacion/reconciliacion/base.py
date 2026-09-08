"""Contratos seguros de procedencia y reconciliación."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.referencias import HallazgoCobertura, ReferenciaCampo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

__all__ = [
    "HallazgoCobertura",
    "InventariadorDocumento",
    "ReconciliadorDocumento",
    "ReferenciaCampo",
]


@runtime_checkable
class ReconciliadorDocumento(Protocol):
    """Strategy que aprueba un documento o lanza `ErrorParseo`."""

    tipo_documento: TipoDocumento

    def reconciliar(self, documento: DocumentoParseado, texto: TextoExtraido) -> tuple[str, ...]:
        """Comprueba la procedencia y fidelidad del documento parseado.

        Devuelve los `id_campo` (vocabulario cerrado, ver `dominio/referencias.py`)
        que el PDF trae y el modelo no citó -- caso benigno de
        `CodigoErrorDocumento.CAMPO_NO_EXTRAIDO` (ver su docstring). Una
        tupla vacía significa "documento completo". El llamador (`pipeline/
        ejecutor.py`) la adjunta a la marca de completitud del registro
        publicado; nunca lanza por sí sola.
        """
        ...


@runtime_checkable
class InventariadorDocumento(Protocol):
    """Strategy que reconoce cobertura desde el PDF, sin consultar el parseo."""

    tipo_documento: TipoDocumento

    def inventariar(self, texto: TextoExtraido) -> tuple[HallazgoCobertura, ...]:
        """Devuelve solo metadata segura de datos clínicos reconocibles."""
        ...
