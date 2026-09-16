"""Extracción de texto nativo de un PDF con PyMuPDF, sin OCR.
Un PDF corrupto o sin texto extraíble falla explícito vía `ErrorParseo` (`PDF_ILEGIBLE`/`SIN_CAPA_DE_TEXTO`)."""

# Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix: extracción con
# sort=True + firmas ECG reales"): `page.get_text()` sin argumentos da el orden de DIBUJADO del
# content stream, no el orden de lectura visual. Contra lab/eco reales, el generador dibuja
# primero todas las etiquetas de una columna y después los valores de la otra -- etiqueta y
# valor quedan lejos en el texto aunque compartan fila visual. `page.get_text(sort=True)` los
# reordena por posición geométrica y los deja adyacentes, que es lo que esperan los regex
# "Etiqueta: valor" de `parseo/laboratorio_general.py` y `parseo/eco_doppler.py`.
#
# Contra el ECG real, en cambio, `sort=True` EMPEORA el resultado: el trazado de las 12
# derivaciones se superpone geométricamente al header y confunde el reordenamiento posicional.
# Por eso `TextoExtraido` expone ambas representaciones (`paginas` sin ordenar para ECG,
# `paginas_ordenadas` para lab/eco) en vez de elegir una sola por heurística.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO

import pymupdf

from ..dominio.errores import CodigoErrorDocumento, ErrorParseo
from .trazos_pymupdf import CapturadorDePagina, Trazo

_ETAPA = "extraccion"


@dataclass(frozen=True)
class TextoExtraido:
    """Texto nativo extraído de un PDF, una entrada por página, en orden.
    `paginas`: sin ordenar (ECG); `paginas_ordenadas`: orden geométrico (lab/eco)."""

    # Detección de tipo lee siempre `paginas` (orden de dibujado). Medido contra el ECG real:
    # orden de dibujado 3/4 marcadores ('12SL','P-R-T AXES','VENT. RATE'); orden geométrico 1/4
    # ('12SL' solo) -- el trazado de las 12 derivaciones se superpone al header y parte los otros
    # 3 en `paginas_ordenadas`. Cambiar detectar_tipo a paginas_ordenadas no reconocería ningún ECG.
    paginas: tuple[str, ...]
    # Si no se provee, se asume igual a `paginas` (construcción directa desde tests).
    paginas_ordenadas: tuple[str, ...] = ()
    trazos: tuple[Trazo, ...] = ()
    """Trazado vectorial negro capturado (sólo ECG, vía `capturador_para`).
    Vacío para laboratorio/ecocardiograma y para cualquier construcción
    directa (tests) que no pase `capturador_para`."""

    def __post_init__(self) -> None:
        if not self.paginas_ordenadas:
            object.__setattr__(self, "paginas_ordenadas", self.paginas)

    @property
    def texto_completo(self) -> str:
        """Todas las páginas (orden de dibujado) concatenadas; detección de tipo/PII."""
        return "\n".join(self.paginas)

    @property
    def texto_completo_ordenado(self) -> str:
        """Todas las páginas (orden geométrico) concatenadas; parseo de lab/eco."""
        return "\n".join(self.paginas_ordenadas)


def extraer_texto_de_flujo(
    flujo: BinaryIO,
    *,
    capturador_para: Callable[[TextoExtraido], CapturadorDePagina | None] | None = None,
) -> TextoExtraido:
    """Extrae el texto nativo de un PDF ya abierto como flujo de bytes.
    `capturador_para`, si se provee, decide sobre el mismo `TextoExtraido` si captura geometría."""
    datos = flujo.read()
    try:
        documento = pymupdf.open(stream=datos, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError) as _exc:
        raise ErrorParseo(codigo=CodigoErrorDocumento.PDF_ILEGIBLE, etapa=_ETAPA) from _exc

    try:
        if documento.page_count == 0:
            # Estructuralmente roto (ni una página), distinto de SIN_CAPA_DE_TEXTO (abajo).
            raise ErrorParseo(codigo=CodigoErrorDocumento.PDF_ILEGIBLE, etapa=_ETAPA)

        paginas = tuple(pagina.get_text() for pagina in documento)
        paginas_ordenadas = tuple(pagina.get_text(sort=True) for pagina in documento)

        if not any(texto.strip() for texto in paginas):
            # Escaneo sin capa de texto: acción distinta de PDF_ILEGIBLE (OCR, no pedir de nuevo).
            raise ErrorParseo(codigo=CodigoErrorDocumento.SIN_CAPA_DE_TEXTO, etapa=_ETAPA)

        texto = TextoExtraido(paginas=paginas, paginas_ordenadas=paginas_ordenadas)

        if capturador_para is not None:
            capturador = capturador_para(texto)
            if capturador is not None:
                trazos = tuple(
                    trazo for pagina in documento for trazo in capturador(pagina)
                )
                texto = replace(texto, trazos=trazos)
    finally:
        documento.close()

    return texto


def extraer_texto(ruta: Path) -> TextoExtraido:
    """Conveniencia de CLI y tests: abre `ruta` y delega en `extraer_texto_de_flujo`.
    El pipeline real usa `extraer_texto_de_flujo` directo sobre el `BinaryIO` de `fuente.abrir`."""
    try:
        with ruta.open("rb") as flujo:
            return extraer_texto_de_flujo(flujo)
    except FileNotFoundError as _exc:
        raise ErrorParseo(codigo=CodigoErrorDocumento.PDF_ILEGIBLE, etapa=_ETAPA) from _exc
