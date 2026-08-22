"""Contratos seguros de procedencia y reconciliación."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.referencias import validar_campo_reconciliacion, validar_selector_reconciliacion
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

@dataclass(frozen=True)
class ReferenciaCampo:
    """Localización no sensible de un campo dentro del texto extraído."""

    id_campo: str
    pagina: int
    selector: str
    ordinal: int = 0

    def __post_init__(self) -> None:
        validar_campo_reconciliacion(self.id_campo)
        validar_selector_reconciliacion(self.id_campo, self.selector)
        if self.pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        if self.ordinal < 0:
            raise ValueError("ordinal no puede ser negativo")


@dataclass(frozen=True)
class HallazgoCobertura:
    """Dato clínico reconocido sin retener su contenido ni PII."""

    id_campo: str
    pagina: int
    ordinal: int = 0
    clase: str = "dato"

    def __post_init__(self) -> None:
        validar_campo_reconciliacion(self.id_campo)
        if self.pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        if self.ordinal < 0:
            raise ValueError("ordinal no puede ser negativo")
        if self.clase not in {"dato", "header", "medida", "coleccion", "seccion"}:
            raise ValueError("clase inválida")


@runtime_checkable
class ReconciliadorDocumento(Protocol):
    """Strategy que aprueba un documento o lanza `ErrorParseo`."""

    tipo_documento: TipoDocumento

    def reconciliar(self, documento: DocumentoParseado, texto: TextoExtraido) -> None:
        """Comprueba la procedencia y fidelidad del documento parseado."""
        ...


@runtime_checkable
class InventariadorDocumento(Protocol):
    """Strategy que reconoce cobertura desde el PDF, sin consultar el parseo."""

    tipo_documento: TipoDocumento

    def inventariar(self, texto: TextoExtraido) -> tuple[HallazgoCobertura, ...]:
        """Devuelve solo metadata segura de datos clínicos reconocibles."""
        ...
