"""Captura de trazos vectoriales negros de una página (extracción del ECG).

Fijado por `tests/extraccion/test_trazos_pymupdf.py` (decisión #1 del
diseño, openspec `senal-ecg-y-dataset-vinculado`): `get_drawings()` ya
entrega las coordenadas SIN ROTAR (espacio del `mediabox`), donde el tiempo
corre por el eje vertical -- aplicar `page.derotation_matrix` o
`page.rotation_matrix` estropea ese eje. Por eso este módulo NO transforma
ninguna coordenada: usa la salida de `get_drawings()` directa, sólo
convertida de puntos PDF a milímetros.

Nunca lee texto -- sólo geometría (design.md, decisión #2).
"""

from __future__ import annotations

import pymupdf

_NEGRO = (0.0, 0.0, 0.0)
_PT_A_MM = 25.4 / 72

Punto = tuple[float, float]
Trazo = tuple[Punto, ...]


def capturar_trazos(pagina: pymupdf.Page) -> tuple[Trazo, ...]:
    """Trazos negros (0,0,0) sin relleno de `pagina`, en mm.

    Cada trazo es una tupla de puntos `(x_mm, y_mm)` en el orden dibujado.
    Ignora cualquier dibujo con color distinto de negro o con relleno
    (p. ej. la grilla rosa del ECG, que usa otro color).
    """
    trazos: list[Trazo] = []
    for dibujo in pagina.get_drawings():
        if dibujo.get("color") != _NEGRO or dibujo.get("fill") is not None:
            continue
        puntos = _puntos_de_items(dibujo["items"])
        if puntos:
            trazos.append(tuple(_a_mm(punto) for punto in puntos))
    return tuple(trazos)


def _puntos_de_items(items: list[tuple]) -> list[pymupdf.Point]:
    """Reconstruye la secuencia de puntos de un trazo a partir de sus
    segmentos de línea (`'l'`). Otros tipos de item (curvas, rectángulos) no
    aplican a un trazado de ECG y se ignoran."""
    puntos: list[pymupdf.Point] = []
    for item in items:
        tipo, *coords = item
        if tipo != "l":
            continue
        inicio, fin = coords
        if not puntos:
            puntos.append(inicio)
        puntos.append(fin)
    return puntos


def _a_mm(punto: pymupdf.Point) -> Punto:
    return (punto.x * _PT_A_MM, punto.y * _PT_A_MM)
