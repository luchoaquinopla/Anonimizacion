"""Fija la decisión #1 del diseño (`senal-ecg-y-dataset-vinculado`):
`get_drawings()` sobre una página rotada 90° -- ¿coordenadas rotadas o sin
rotar respecto de `page.derotation_matrix`?

Medido con un rectángulo conocido en una página `mediabox` 612x792 con
`set_rotation(90)`: `get_drawings()` devuelve el rectángulo TAL COMO SE
DIBUJÓ, en el espacio del `mediabox` (sin rotar) -- NO en el espacio visible
`page.rect` (rotado, 792x612). Aplicar `page.derotation_matrix` a ese
resultado lo estropea (convierte el eje alto/tiempo en ancho); aplicar
`page.rotation_matrix` lo lleva al espacio visible rotado, tampoco el que
necesita el algoritmo (design.md: "el tiempo es el eje vertical sin
rotar"). Conclusión: `trazos_pymupdf.py` NO debe transformar nada -- usa las
coordenadas de `get_drawings()` directas.
"""

from __future__ import annotations

import pymupdf

from anonimizacion.extraccion.trazos_pymupdf import capturar_trazos


def _pagina_ecg_rotada() -> pymupdf.Page:
    documento = pymupdf.open()
    pagina = documento.new_page(width=612, height=792)
    pagina.set_rotation(90)
    return pagina


def test_get_drawings_devuelve_coordenadas_sin_rotar_del_mediabox() -> None:
    pagina = _pagina_ecg_rotada()
    rect_dibujado = pymupdf.Rect(10, 10, 50, 700)
    trazo = pagina.new_shape()
    trazo.draw_rect(rect_dibujado)
    trazo.finish(color=(0, 0, 0), fill=None)
    trazo.commit()

    dibujos = pagina.get_drawings()

    assert len(dibujos) == 1
    assert dibujos[0]["rect"] == rect_dibujado
    # el mediabox (sin rotar) es 612x792 -- el rect dibujado cabe ahí, no en
    # `page.rect` (792x612, espacio visible rotado)
    assert pagina.mediabox.contains(dibujos[0]["rect"])
    assert not pagina.rect.contains(dibujos[0]["rect"])


def test_derotation_matrix_no_se_debe_aplicar_estropea_el_eje_de_tiempo() -> None:
    """`derotation_matrix` asume que la entrada YA está en espacio rotado
    (visible) -- aplicarla a algo que ya está sin rotar convierte la altura
    (eje de tiempo, design.md) en ancho. Documenta por qué
    `trazos_pymupdf.py` no debe usarla."""
    pagina = _pagina_ecg_rotada()
    rect_dibujado = pymupdf.Rect(10, 10, 50, 700)
    trazo = pagina.new_shape()
    trazo.draw_rect(rect_dibujado)
    trazo.finish(color=(0, 0, 0), fill=None)
    trazo.commit()

    rect_crudo = pagina.get_drawings()[0]["rect"]
    rect_con_derotacion_indebida = rect_crudo * pagina.derotation_matrix

    assert rect_crudo.height == 690  # eje de tiempo correcto: alto del mediabox
    assert rect_con_derotacion_indebida.height != 690


def test_capturar_trazos_recupera_polilinea_negra_en_mm() -> None:
    documento = pymupdf.open()
    pagina = documento.new_page(width=612, height=792)
    puntos_pt = [(72.0, 72.0), (144.0, 144.0), (216.0, 72.0)]
    trazo = pagina.new_shape()
    trazo.draw_polyline(puntos_pt)
    trazo.finish(color=(0, 0, 0), fill=None, width=0.43, closePath=False)
    trazo.commit()

    trazos = capturar_trazos(pagina)

    assert len(trazos) == 1
    esperado = tuple((x * 25.4 / 72, y * 25.4 / 72) for x, y in puntos_pt)
    assert trazos[0] == esperado


def test_capturar_trazos_ignora_dibujos_no_negros_o_con_relleno() -> None:
    documento = pymupdf.open()
    pagina = documento.new_page(width=612, height=792)

    grilla = pagina.new_shape()
    grilla.draw_line((0, 0), (100, 0))
    grilla.finish(color=(1, 0.7, 0.7), width=0.03)  # grilla rosa
    grilla.commit()

    relleno = pagina.new_shape()
    relleno.draw_rect(pymupdf.Rect(10, 10, 20, 20))
    relleno.finish(color=(0, 0, 0), fill=(0, 0, 0))  # negro pero con relleno
    relleno.commit()

    assert capturar_trazos(pagina) == ()
