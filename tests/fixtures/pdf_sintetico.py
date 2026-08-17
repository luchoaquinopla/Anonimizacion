"""Generador de PDFs sintéticos para tests de extracción/detección.

Todo el texto usado (nombres, DNI, valores) es inventado para estos tests,
nunca proviene de los PDFs de muestra reales. Se genera con `pymupdf`
(la misma librería que usa `extraccion.texto_pymupdf`) para no sumar una
dependencia de test adicional (p. ej. reportlab).
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def crear_pdf_con_texto(ruta: Path, paginas: list[str]) -> Path:
    """Crea un PDF con una página por cada string de `paginas` (texto nativo)."""
    documento = pymupdf.open()
    for texto in paginas:
        pagina = documento.new_page()
        if texto:
            pagina.insert_text((72, 72), texto, fontsize=11)
    documento.save(ruta)
    documento.close()
    return ruta


def crear_pdf_corrupto(ruta: Path) -> Path:
    """Escribe bytes que no son un PDF válido, simulando un archivo corrupto."""
    ruta.write_bytes(b"esto no es un pdf valido, solo bytes sinteticos de prueba")
    return ruta


def crear_pdf_layout_columnas(
    ruta: Path,
    filas: list[tuple[str, str]],
    *,
    y_inicio: float = 100,
    alto_fila: float = 20,
) -> Path:
    """Crea un PDF de una página con `filas` de (etiqueta, valor) en dos columnas.

    Replica el artefacto de generación real observado contra los PDFs de
    muestra (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
    extracción con sort=True"): el content stream dibuja PRIMERO todas las
    etiquetas de la columna izquierda y DESPUÉS todos los valores de la
    columna derecha, aunque geométricamente cada etiqueta y su valor
    comparten la misma fila (misma altura `y`). El orden de dibujado (el que
    devuelve `page.get_text()` sin `sort=True`) NO es el orden de lectura
    visual: etiqueta y valor quedan muy separados entre sí. Con
    `page.get_text(sort=True)` (orden geométrico) quedan adyacentes en la
    misma línea, como espera un lector humano.
    """
    documento = pymupdf.open()
    pagina = documento.new_page()
    x_etiqueta, x_valor = 72, 250
    for indice, (etiqueta, _valor) in enumerate(filas):
        pagina.insert_text((x_etiqueta, y_inicio + indice * alto_fila), etiqueta, fontsize=11)
    for indice, (_etiqueta, valor) in enumerate(filas):
        pagina.insert_text((x_valor, y_inicio + indice * alto_fila), valor, fontsize=11)
    documento.save(ruta)
    documento.close()
    return ruta
