"""`ParseadorDocumento`: contrato Protocol que implementa cada parser de layout.

Fase 4 recibe el `TextoExtraido` de Fase 2 y el `TipoDocumento` ya resuelto
por Fase 3 (`detectar_tipo`); un `ParseadorDocumento` por tipo conocido
transforma ese texto en un `DocumentoParseado` tipado. Es Protocol (no ABC)
para no forzar herencia: cualquier objeto con esta forma sirve, plugins
incluidos (ver design.md, "Parsers como plugins registrados": un layout
nuevo es una clase nueva, no un cambio de core).

Deviación de design.md: el Protocol del design incluye `confidence(texto) ->
float` para que el propio parser opine sobre si sabe leer el documento. Acá
se omite: la Fase 3 (`detectar_tipo`) ya resuelve el tipo de forma completa
antes de llegar a esta etapa (una firma por tipo, sin ambigüedad), así que
un método de confianza en el parser sería código muerto en este pipeline.
Si en el futuro se necesita desambiguar entre parsers candidatos, se agrega
sin romper este contrato (evolución aditiva, mismo principio que
`EcgPayload.waveform` en el design).
"""

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
