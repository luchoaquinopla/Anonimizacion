"""Integración extremo a extremo: PDF sintético de ECG (rotado 90°) ->
`capturar_trazos` -> `construir_senal`.

Oráculo INDEPENDIENTE (no autoconfirmatorio): el pico/valle esperado en
`_forma_pico_valle` no comparte fórmula con `construir_senal` -- son
plateaus a valores fijos, no una expresión algebraica que dependa de la
misma convención de signo que el código bajo prueba. Antes, el fixture
dibujaba `x = centro + mv * escala` y el extractor asumía `mv = (x -
centro) / escala`: si el signo real del PDF fuera al revés, ambos lados
coincidían igual y el bug (amplitud invertida) no se notaba. Ahora
`crear_pdf_ecg_con_trazos_sinteticos(escala_mm_por_mv=...)` es un parámetro
explícito del fixture, y `construir_senal` NUNCA asume una dirección: la
lee del pulso de calibración de cada banda.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf

from anonimizacion.extraccion.senal_ecg import MUESTRAS_DERIVACION, construir_senal
from anonimizacion.extraccion.trazos_pymupdf import capturar_trazos
from tests.fixtures.pdf_sintetico import crear_pdf_ecg_con_trazos_sinteticos


def _forma_pico_valle(n: int, *, ancho: int = 5) -> list[float]:
    """Oráculo independiente: dos plateaus a valores fijos conocidos, en
    tiempos distintos -- +1,5 mV cerca de 1/4 de la ventana, -0,5 mV cerca
    de 3/4. El resto queda en la línea base (0 mV)."""
    valores = [0.0] * n
    centro_pico, centro_valle = n // 4, (3 * n) // 4
    for indice in range(centro_pico - ancho, centro_pico + ancho):
        valores[indice] = 1.5
    for indice in range(centro_valle - ancho, centro_valle + ancho):
        valores[indice] = -0.5
    return valores


def _recuperar_senal(ruta: Path) -> object:
    documento = pymupdf.open(ruta)
    try:
        trazos = capturar_trazos(documento[0])
    finally:
        documento.close()
    assert len(trazos) == 17
    return construir_senal(trazos)


def test_pdf_sintetico_ecg_recupera_signo_amplitud_y_linea_base(tmp_path: Path) -> None:
    ruta = tmp_path / "ecg_sintetico.pdf"
    forma = _forma_pico_valle(MUESTRAS_DERIVACION)
    crear_pdf_ecg_con_trazos_sinteticos(ruta, semilla=7, oraculo_por_derivacion={"I": forma})

    senal = _recuperar_senal(ruta)

    assert senal is not None
    recuperado_mv = senal.muestras_uv[0, 0:MUESTRAS_DERIVACION] / 1000.0
    esperado_mv = np.array(forma)
    error_maximo = np.max(np.abs(recuperado_mv - esperado_mv))
    assert error_maximo <= 0.01, f"error {error_maximo} mV -- signo o línea base mal derivados"

    # línea base explícita: fuera de los dos plateaus, la derivación debe quedar en ~0 mV
    fuera_de_plateaus = np.abs(esperado_mv) < 1e-9
    assert np.max(np.abs(recuperado_mv[fuera_de_plateaus])) <= 0.01


def test_pdf_sintetico_ecg_sigue_la_direccion_del_pulso_invertido(tmp_path: Path) -> None:
    """Si TODOS los pulsos apuntan al revés del real (+1 mV = +10 mm en vez
    de -10 mm), `construir_senal` debe seguir esa dirección -- la lee del
    pulso, nunca de una constante fija."""
    ruta = tmp_path / "ecg_invertido.pdf"
    forma = _forma_pico_valle(MUESTRAS_DERIVACION)
    crear_pdf_ecg_con_trazos_sinteticos(
        ruta, semilla=7, escala_mm_por_mv=10.0, oraculo_por_derivacion={"I": forma}
    )

    senal = _recuperar_senal(ruta)

    assert senal is not None
    recuperado_mv = senal.muestras_uv[0, 0:MUESTRAS_DERIVACION] / 1000.0
    error_maximo = np.max(np.abs(recuperado_mv - np.array(forma)))
    assert error_maximo <= 0.01


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
