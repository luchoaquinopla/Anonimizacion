"""Integración extremo a extremo: PDF sintético de ECG (rotado 90°, con
oráculo) -> `capturar_trazos` -> `construir_senal`.

Criterio de éxito de la propuesta: error <= 0.01 mV contra el oráculo en
cada derivación. A diferencia de `tests/extraccion/test_senal_ecg.py`
(trazos armados a mano), acá el trazado sale de un PDF real escrito a
disco y leído con `pymupdf`, ejercitando `capturar_trazos` también.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf

from anonimizacion.extraccion.senal_ecg import (
    MUESTRAS_DERIVACION,
    MUESTRAS_TIRA,
    OFFSETS_COLUMNA,
    ORDEN_DERIVACIONES,
    construir_senal,
)
from anonimizacion.extraccion.trazos_pymupdf import capturar_trazos
from tests.fixtures.pdf_sintetico import crear_pdf_ecg_con_trazos_sinteticos


def test_pdf_sintetico_ecg_recupera_senal_con_error_menor_a_01mv(tmp_path: Path) -> None:
    ruta = tmp_path / "ecg_sintetico.pdf"
    oraculo = crear_pdf_ecg_con_trazos_sinteticos(ruta, semilla=7)

    documento = pymupdf.open(ruta)
    try:
        trazos = capturar_trazos(documento[0])
    finally:
        documento.close()

    assert len(trazos) == 17  # 12 derivaciones + 1 tira + 4 pulsos; la grilla rosa queda afuera

    senal = construir_senal(trazos)

    assert senal is not None
    indice_v1 = ORDEN_DERIVACIONES.index("V1")

    for columna in range(4):
        for fila in range(3):
            indice_lead = columna * 3 + fila
            if indice_lead == indice_v1:
                continue
            derivacion = ORDEN_DERIVACIONES[indice_lead]
            inicio = OFFSETS_COLUMNA[columna]
            recuperado_mv = senal.muestras_uv[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] / 1000.0
            esperado_mv = np.array(oraculo[derivacion])
            error_maximo = np.max(np.abs(recuperado_mv - esperado_mv))
            assert error_maximo <= 0.01, f"{derivacion}: error {error_maximo} mV"

    recuperado_tira_mv = senal.muestras_uv[indice_v1, :] / 1000.0
    esperado_tira_mv = np.array(oraculo["tira_ritmo"])
    assert np.max(np.abs(recuperado_tira_mv[:MUESTRAS_TIRA] - esperado_tira_mv)) <= 0.01


def test_pdf_sintetico_ecg_ignora_la_grilla_rosa_de_calibracion(tmp_path: Path) -> None:
    ruta = tmp_path / "ecg_sintetico.pdf"
    crear_pdf_ecg_con_trazos_sinteticos(ruta, semilla=3)

    documento = pymupdf.open(ruta)
    try:
        dibujos_rosas = [
            d
            for d in documento[0].get_drawings()
            if d.get("color") is not None and d["color"][0] > 0.9 and 0.6 < d["color"][1] < 0.8
        ]
        trazos = capturar_trazos(documento[0])
    finally:
        documento.close()

    assert len(dibujos_rosas) > 0  # la grilla efectivamente se dibujó...
    assert len(trazos) == 17  # ...pero capturar_trazos no la incluyó
