"""Tests de extracción de texto nativo con PyMuPDF (spec: pdf-text-extraction).

Cubre: texto nativo sin OCR (multi-página, tipo laboratorio), texto sparse
tipo ECG con trazado rasterizado (la traza no tiene texto, pero el header sí,
y eso NO debe fallar), y fallo explícito ante PDF corrupto / sin texto
extraíble.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido, extraer_texto
from tests.fixtures.pdf_sintetico import (
    crear_pdf_con_texto,
    crear_pdf_corrupto,
    crear_pdf_layout_columnas,
)


def test_extraer_texto_lab_multi_pagina_devuelve_texto_por_pagina(tmp_path: Path) -> None:
    ruta = crear_pdf_con_texto(
        tmp_path / "lab.pdf",
        paginas=[
            "HEMATOLOGIA\nHematocrito 42%\nHemoglobina 14 g/dL",
            "QUIMICA CLINICA\nGlucosa 90 mg/dL",
        ],
    )

    resultado = extraer_texto(ruta)

    assert isinstance(resultado, TextoExtraido)
    assert len(resultado.paginas) == 2
    assert "HEMATOLOGIA" in resultado.paginas[0]
    assert "QUIMICA CLINICA" in resultado.paginas[1]


def test_extraer_texto_ecg_con_trazado_rasterizado_no_falla_por_texto_sparse(
    tmp_path: Path,
) -> None:
    # simula un ECG Mortara: solo el header trae texto nativo, la traza es una imagen
    ruta = crear_pdf_con_texto(tmp_path / "ecg.pdf", paginas=["MORTARA\nVent rate 72 bpm"])

    resultado = extraer_texto(ruta)

    assert len(resultado.paginas) == 1
    assert "MORTARA" in resultado.paginas[0]


def test_extraer_texto_pdf_corrupto_falla_explicito(tmp_path: Path) -> None:
    ruta = crear_pdf_corrupto(tmp_path / "corrupto.pdf")

    with pytest.raises(ErrorParseo) as exc_info:
        extraer_texto(ruta)

    assert exc_info.value.codigo == CodigoErrorDocumento.PARSEO_INCOMPLETO
    assert exc_info.value.etapa == "extraccion"


def test_extraer_texto_sin_texto_extraible_falla_explicito(tmp_path: Path) -> None:
    ruta = crear_pdf_con_texto(tmp_path / "vacio.pdf", paginas=["", ""])

    with pytest.raises(ErrorParseo) as exc_info:
        extraer_texto(ruta)

    assert exc_info.value.codigo == CodigoErrorDocumento.PARSEO_INCOMPLETO


def test_extraer_texto_archivo_inexistente_falla_explicito(tmp_path: Path) -> None:
    with pytest.raises(ErrorParseo) as exc_info:
        extraer_texto(tmp_path / "no_existe.pdf")

    assert exc_info.value.codigo == CodigoErrorDocumento.PARSEO_INCOMPLETO


def test_extraer_texto_paginas_ordenadas_agrupa_etiqueta_y_valor_en_la_misma_linea(
    tmp_path: Path,
) -> None:
    # replica el layout real de laboratorio: etiquetas dibujadas primero,
    # valores dibujados despues, pero geometricamente en la misma fila
    ruta = crear_pdf_layout_columnas(
        tmp_path / "columnas.pdf",
        filas=[
            ("Apellido y Nombre:", "PEREZ JUAN"),
            ("Fecha:", "01/01/2026"),
            ("Edad:", "64"),
        ],
    )

    resultado = extraer_texto(ruta)

    # sin ordenar (orden de dibujado): etiquetas agrupadas, lejos de sus valores
    sin_ordenar = resultado.paginas[0]
    assert sin_ordenar.find("Apellido y Nombre:") < sin_ordenar.find("Fecha:")
    assert sin_ordenar.find("Fecha:") < sin_ordenar.find("PEREZ JUAN")

    # ordenada geometricamente: etiqueta y su valor quedan en la misma linea
    assert len(resultado.paginas_ordenadas) == 1
    linea_nombre = next(
        linea
        for linea in resultado.paginas_ordenadas[0].splitlines()
        if "Apellido y Nombre" in linea
    )
    assert "PEREZ JUAN" in linea_nombre

    linea_fecha = next(
        linea for linea in resultado.paginas_ordenadas[0].splitlines() if "Fecha:" in linea
    )
    assert "01/01/2026" in linea_fecha


def test_extraer_texto_completo_ordenado_concatena_paginas_ordenadas(tmp_path: Path) -> None:
    ruta = crear_pdf_con_texto(
        tmp_path / "lab.pdf",
        paginas=["HEMATOLOGIA\nHematocrito 42%", "QUIMICA CLINICA\nGlucosa 90 mg/dL"],
    )

    resultado = extraer_texto(ruta)

    assert resultado.texto_completo_ordenado == "\n".join(resultado.paginas_ordenadas)
