"""Captura de trazos vectoriales negros de una página (extracción del ECG).
`get_drawings()` entrega coordenadas sin rotar; nunca lee texto, sólo geometría.
No aplicar `derotation_matrix`/`rotation_matrix`: estropea el eje del tiempo."""

from __future__ import annotations

from collections.abc import Callable

import pymupdf

_NEGRO = (0.0, 0.0, 0.0)
_PT_A_MM = 25.4 / 72
# Ancho de trazo medido contra el ECG real, con margen ±20% por redondeo del renderer.
# Invariante: «Calibración del trazado del ECG» (Obsidian, Invariantes medidos).
_ANCHO_TRAZO_PT = 0.43
_TOLERANCIA_ANCHO = 0.20

Punto = tuple[float, float]
Trazo = tuple[Punto, ...]
CapturadorDePagina = Callable[[pymupdf.Page], tuple[Trazo, ...]]


def capturar_trazos(pagina: pymupdf.Page) -> tuple[Trazo, ...]:
    """Trazos negros, sin relleno, de ancho ≈0,43pt de `pagina`, en mm.
    Ignora cualquier dibujo con color/relleno/ancho distinto (p. ej. la grilla rosa)."""
    trazos: list[Trazo] = []
    for dibujo in pagina.get_drawings():
        if dibujo.get("color") != _NEGRO or dibujo.get("fill") is not None:
            continue
        ancho = dibujo.get("width")
        if ancho is None or abs(ancho - _ANCHO_TRAZO_PT) / _ANCHO_TRAZO_PT > _TOLERANCIA_ANCHO:
            continue
        puntos = _puntos_de_items(dibujo["items"])
        if puntos:
            trazos.append(tuple(_a_mm(punto) for punto in puntos))
    return tuple(trazos)


def _puntos_de_items(items: list[tuple]) -> list[pymupdf.Point]:
    """Reconstruye la secuencia de puntos de un trazo a partir de sus segmentos de línea ('l')."""
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
