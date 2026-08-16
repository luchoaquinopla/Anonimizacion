"""Extracción de texto nativo de un PDF con PyMuPDF, sin OCR.

Spec `pdf-text-extraction`: solo se lee el texto que el PDF ya trae embebido
(capa de texto nativa). Un PDF con trazado rasterizado (p. ej. la traza de un
ECG, que es una imagen) es válido mientras algo de texto nativo exista en
algún lado (típicamente el header); un PDF corrupto o totalmente sin texto
extraíble falla explícito, vía `ErrorParseo`, para no propagar datos vacíos
silenciosamente etapas abajo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ..dominio.errores import CodigoErrorDocumento, ErrorParseo

_ETAPA = "extraccion"


@dataclass(frozen=True)
class TextoExtraido:
    """Texto nativo extraído de un PDF, una entrada por página, en orden."""

    paginas: tuple[str, ...]

    @property
    def texto_completo(self) -> str:
        """Todas las páginas concatenadas; útil para detección de tipo/PII."""
        return "\n".join(self.paginas)


def extraer_texto(ruta: Path) -> TextoExtraido:
    """Extrae el texto nativo de `ruta`. Lanza `ErrorParseo` si no es posible."""
    try:
        documento = pymupdf.open(ruta)
    except (pymupdf.FileDataError, FileNotFoundError, RuntimeError) as _exc:
        raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA) from _exc

    try:
        if documento.page_count == 0:
            raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)

        paginas = tuple(pagina.get_text() for pagina in documento)
    finally:
        documento.close()

    if not any(texto.strip() for texto in paginas):
        raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)

    return TextoExtraido(paginas=paginas)
