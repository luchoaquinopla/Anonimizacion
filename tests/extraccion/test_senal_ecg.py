"""Tests de `construir_senal` (openspec `senal-ecg-y-dataset-vinculado`,
design.md "Algoritmo"): polilíneas sintéticas equiespaciadas, no
equiespaciadas, y cada violación de layout.

Nunca se construye a partir de un PDF acá -- eso es tarea 1.5
(`tests/fixtures/test_pdf_sintetico_ecg.py`), contra el generador con
oráculo. Estos tests ejercitan `construir_senal` directo sobre trazos
(listas de puntos en mm) armados a mano, más rápido y más preciso para
cubrir cada rama de validación.
"""

from __future__ import annotations

import math

import numpy as np

from anonimizacion.extraccion.senal_ecg import (
    FRECUENCIA_HZ,
    MM_POR_S,
    MUESTRAS_DERIVACION,
    MUESTRAS_TIRA,
    OFFSETS_COLUMNA,
    ORDEN_DERIVACIONES,
    construir_senal,
)

# columna -> Y de inicio (mm), fila -> X de centro (mm): bien separados
_Y_COLUMNA = tuple(offset / FRECUENCIA_HZ * MM_POR_S for offset in OFFSETS_COLUMNA)
_X_FILA = (50.0, 100.0, 150.0)


def _trazo_desde_mv(
    valores_mv: list[float], *, y0_mm: float, x_centro_mm: float, frecuencia: int = FRECUENCIA_HZ
) -> tuple[tuple[float, float], ...]:
    return tuple(
        (x_centro_mm + mv * 10.0, y0_mm + indice / frecuencia * MM_POR_S)
        for indice, mv in enumerate(valores_mv)
    )


def _pulso(y0_mm: float, x_centro_mm: float, altura_mv: float = 1.0) -> tuple[tuple[float, float], ...]:
    valores = [0.0] * 5 + [altura_mv] * 55
    return _trazo_desde_mv(valores, y0_mm=y0_mm, x_centro_mm=x_centro_mm)


def _onda_seno(n: int, amplitud_mv: float = 0.5) -> list[float]:
    return [amplitud_mv * math.sin(2 * math.pi * 3 * i / n) for i in range(n)]


def _corpus_valido() -> tuple[tuple[tuple[float, float], ...], ...]:
    """17 trazos: 12 derivaciones + 1 tira + 4 pulsos, en grilla válida."""
    trazos: list[tuple[tuple[float, float], ...]] = []
    for columna in range(4):
        for fila in range(3):
            valores = _onda_seno(MUESTRAS_DERIVACION, amplitud_mv=0.3 + 0.05 * fila)
            trazos.append(
                _trazo_desde_mv(valores, y0_mm=_Y_COLUMNA[columna], x_centro_mm=_X_FILA[fila])
            )
    trazos.append(_trazo_desde_mv(_onda_seno(MUESTRAS_TIRA, amplitud_mv=0.4), y0_mm=0.0, x_centro_mm=_X_FILA[0]))
    for columna in range(4):
        trazos.append(_pulso(_Y_COLUMNA[columna], x_centro_mm=200.0))
    return tuple(trazos)


def test_construir_senal_recupera_oraculo_equiespaciado() -> None:
    senal = construir_senal(_corpus_valido())

    assert senal is not None
    assert senal.muestras_uv.shape == (12, 5000)
    assert senal.mascara.shape == (12, 5000)
    indice_v1 = ORDEN_DERIVACIONES.index("V1")
    assert senal.mascara.all(axis=1)[indice_v1]  # tira: fila completa

    # error <= 0.01 mV (10 uV) contra el oráculo, criterio de éxito de la propuesta.
    # V1 se salta acá: su fila la reemplaza por completo la tira de ritmo
    # (design.md, "el tiempo es el eje... la tira de 5000 ocupa las 5000
    # muestras"), se verifica aparte más abajo.
    for columna in range(4):
        for fila in range(3):
            indice_lead = columna * 3 + fila
            if indice_lead == indice_v1:
                continue
            esperado_mv = _onda_seno(MUESTRAS_DERIVACION, amplitud_mv=0.3 + 0.05 * fila)
            inicio = OFFSETS_COLUMNA[columna]
            recuperado_mv = senal.muestras_uv[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] / 1000.0
            error_maximo = np.max(np.abs(recuperado_mv - np.array(esperado_mv)))
            assert error_maximo <= 0.01

    esperado_tira_mv = np.array(_onda_seno(MUESTRAS_TIRA, amplitud_mv=0.4))
    recuperado_tira_mv = senal.muestras_uv[indice_v1, :] / 1000.0
    assert np.max(np.abs(recuperado_tira_mv - esperado_tira_mv)) <= 0.01


def test_construir_senal_recupera_oraculo_no_equiespaciado() -> None:
    """Puntos con desvío de espaciado > 1% -- se interpola a la grilla de
    500 Hz (design.md paso "Conversión")."""
    valores = _onda_seno(MUESTRAS_DERIVACION, amplitud_mv=0.3)
    duracion_s = (MUESTRAS_DERIVACION - 1) / FRECUENCIA_HZ
    # muestreo NO uniforme que cubre la misma ventana temporal total
    tiempos_no_uniformes = sorted(
        {round(duracion_s * (i / (MUESTRAS_DERIVACION - 1)) ** 1.03, 6) for i in range(MUESTRAS_DERIVACION)}
    )
    trazo_no_equiespaciado = tuple(
        (_X_FILA[0] + valores[min(i, len(valores) - 1)] * 10.0, _Y_COLUMNA[0] + t * MM_POR_S)
        for i, t in enumerate(tiempos_no_uniformes)
    )

    trazos = list(_corpus_valido())
    trazos[0] = trazo_no_equiespaciado  # columna 0, fila 0
    senal = construir_senal(tuple(trazos))

    assert senal is not None
    recuperado_mv = senal.muestras_uv[0, 0:MUESTRAS_DERIVACION] / 1000.0
    error_maximo = np.max(np.abs(recuperado_mv - np.array(valores[: len(recuperado_mv)])))
    assert error_maximo <= 0.07  # tolerancia algo mayor: remuestreo desde grilla irregular


def test_construir_senal_falla_si_falta_un_pulso_de_calibracion() -> None:
    trazos = list(_corpus_valido())
    trazos.pop(-1)  # quita un pulso: quedan 3 en vez de 4

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_falta_una_derivacion() -> None:
    trazos = list(_corpus_valido())
    trazos.pop(0)  # quita una derivación: quedan 11 en vez de 12

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_falta_la_tira_de_ritmo() -> None:
    trazos = [t for t in _corpus_valido() if len(t) != MUESTRAS_TIRA]

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_hay_dos_tiras_de_ritmo() -> None:
    trazos = list(_corpus_valido())
    trazos.append(_trazo_desde_mv(_onda_seno(MUESTRAS_TIRA), y0_mm=0.0, x_centro_mm=_X_FILA[1]))

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_el_pulso_no_mide_10mm() -> None:
    trazos = list(_corpus_valido())
    trazos[-1] = _pulso(_Y_COLUMNA[-1], x_centro_mm=200.0, altura_mv=2.0)  # 20mm, no 10mm

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_dos_derivaciones_caen_en_la_misma_celda() -> None:
    """Filas no disjuntas: dos trazos con el mismo Y de inicio y mismo X
    de centro -- viola la grilla 4x3."""
    trazos = list(_corpus_valido())
    trazos[1] = _trazo_desde_mv(_onda_seno(MUESTRAS_DERIVACION), y0_mm=_Y_COLUMNA[0], x_centro_mm=_X_FILA[0])

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_ante_trazo_de_longitud_no_reconocida() -> None:
    trazos = list(_corpus_valido())
    trazos[-1] = tuple((0.0, float(i)) for i in range(300))  # ni pulso, ni derivación, ni tira

    assert construir_senal(tuple(trazos)) is None
