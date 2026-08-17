"""Extracción de texto nativo de un PDF con PyMuPDF, sin OCR.

Spec `pdf-text-extraction`: solo se lee el texto que el PDF ya trae embebido
(capa de texto nativa). Un PDF con trazado rasterizado (p. ej. la traza de un
ECG, que es una imagen) es válido mientras algo de texto nativo exista en
algún lado (típicamente el header); un PDF corrupto o totalmente sin texto
extraíble falla explícito, vía `ErrorParseo`, para no propagar datos vacíos
silenciosamente etapas abajo.

Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
extracción con sort=True + firmas ECG reales"): `page.get_text()` sin
argumentos devuelve el texto en el orden de DIBUJADO del content stream del
PDF, no en orden de lectura visual. Contra los PDFs de muestra reales de
laboratorio/ecocardiograma, el generador dibuja primero TODAS las etiquetas
de una columna y DESPUÉS todos los valores de la otra — etiqueta y valor
terminan lejísimos entre sí en el texto extraído, aunque compartan la misma
fila visualmente. `page.get_text(sort=True)` (parámetro nativo de PyMuPDF)
reordena por posición geométrica y los deja adyacentes en la misma línea,
que es lo que esperan los regex "Etiqueta: valor" de
`parseo/laboratorio_general.py` y `parseo/eco_doppler.py`.

Contra el ECG real, en cambio, `sort=True` EMPEORA el resultado: el trazado
de las 12 derivaciones (gráfico, no texto) se superpone geométricamente al
header y confunde el reordenamiento posicional. `parseo/ecg_mortara.py` ya
fue recalibrado (fix anterior) contra el orden de dibujado SIN `sort=True`.

Por eso `TextoExtraido` expone AMBAS representaciones en vez de elegir una
sola por heurística: `paginas` (orden de dibujado, sin tocar — el ECG sigue
usando esta) y `paginas_ordenadas` (orden geométrico — laboratorio y eco
usan esta). El costo es extraer el texto dos veces por página; para los
tamaños de PDF de este dominio (unas pocas páginas) es despreciable, y evita
adivinar con una heurística "qué orden es mejor" que sería frágil ante un
cuarto tipo de documento futuro con un layout distinto. Cada parser elige
explícitamente qué representación necesita.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ..dominio.errores import CodigoErrorDocumento, ErrorParseo

_ETAPA = "extraccion"


@dataclass(frozen=True)
class TextoExtraido:
    """Texto nativo extraído de un PDF, una entrada por página, en orden.

    `paginas`: orden de dibujado del content stream (sin `sort=True`) — lo
    que espera `parseo/ecg_mortara.py`, recalibrado contra el layout real.
    `paginas_ordenadas`: orden geométrico (`sort=True`) — lo que esperan
    `parseo/laboratorio_general.py` y `parseo/eco_doppler.py`. La detección
    de tipo (`deteccion/detector_tipo.py`) es indistinta a cuál se use: solo
    hace `in` sobre el texto completo en mayúsculas, no depende del orden.

    `paginas_ordenadas` es opcional en la construcción directa (p. ej. desde
    tests que arman un `TextoExtraido` a mano sin pasar por
    `extraer_texto`): si no se provee, se asume igual a `paginas` —
    razonable porque en un layout sintético de una sola línea por campo
    ambas representaciones ya coinciden.
    """

    paginas: tuple[str, ...]
    paginas_ordenadas: tuple[str, ...] = ()

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
        paginas_ordenadas = tuple(pagina.get_text(sort=True) for pagina in documento)
    finally:
        documento.close()

    if not any(texto.strip() for texto in paginas):
        raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)

    return TextoExtraido(paginas=paginas, paginas_ordenadas=paginas_ordenadas)
