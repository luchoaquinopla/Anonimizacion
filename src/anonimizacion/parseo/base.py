"""`ParseadorDocumento`: contrato Protocol que implementa cada parser de layout.
Protocol, no ABC: cualquier objeto con esta forma sirve, plugins incluidos."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido


@runtime_checkable
class ParseadorDocumento(Protocol):
    """Un parser concreto por layout; `tipo_documento` es la clave del registro."""

    tipo_documento: TipoDocumento

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        """Convierte texto extraído en un `DocumentoParseado`; lanza `ErrorParseo` si falla."""
        ...
