"""Tests de `construir_senal` (openspec `senal-ecg-y-dataset-vinculado`,
design.md "Algoritmo"): polilíneas sintéticas equiespaciadas, no
equiespaciadas, y cada violación de layout.

El oráculo de recuperación de signo/amplitud/línea base con forma
independiente vive en `tests/fixtures/test_pdf_sintetico_ecg.py` (contra un
PDF real, no trazos armados a mano). Acá se cubre lo que ese test de
integración no puede cubrir barato: cada rama de validación de layout, y
que el pulso decide la dirección incluso con sus puntos desordenados.
"""

from __future__ import annotations

import math

import numpy as np

from anonimizacion.extraccion.senal_ecg import (
    AMPLITUD_MAXIMA_UV,
    FRECUENCIA_HZ,
    MM_POR_S,
    MUESTRAS_DERIVACION,
    MUESTRAS_TIRA,
    OFFSETS_COLUMNA,
    ORDEN_DERIVACIONES,
    _muestrear,
    construir_senal,
)

# columna -> Y de inicio (mm), fila -> X de referencia (mm) de la banda de
# amplitud; la tira tiene su PROPIA banda, medido: nunca coincide con las
# 3 filas de la grilla (ver tests/fixtures/pdf_sintetico.py). Con el pulso
# por DEBAJO de todo el dato (`_Y_PULSO`), el tiempo avanza con Y creciente
# (`direccion=+1`) -- así `columna` en `_corpus_valido` coincide 1 a 1 con
# el índice temporal real, sin necesidad de invertir nada acá.
_Y_COLUMNA = tuple(offset / FRECUENCIA_HZ * MM_POR_S for offset in OFFSETS_COLUMNA)
_X_FILA = (50.0, 100.0, 150.0)
_X_TIRA = 220.0
_ESCALA_MM_REAL = -10.0  # medido: +1 mV = -10 mm, nunca +10
_Y_PULSO = -30.0  # debajo de todo el dato (Y mínimo de columnas/tira es 0.0)

# Coeficientes que hacen que `_corpus_valido` cumpla Einthoven/Goldberger de
# verdad (no un supuesto): columna 0 = miembros, columna 1 = aumentada,
# columna 2 fila 0 = V1 de grilla (debe coincidir con el segmento
# equivalente de la tira). `_onda_seno` es sin(2*pi*3*i/n) escalado por la
# amplitud -- misma fase para cualquier amplitud, así que una combinación
# lineal de amplitudes es exacta punto a punto.
_COEF_I = 0.30
_COEF_II = 0.50
_COEF_III = _COEF_II - _COEF_I  # Einthoven: III = II - I
_COEF_AVR = -(_COEF_I + _COEF_II) / 2  # Goldberger
_COEF_AVL = _COEF_I - _COEF_II / 2
_COEF_AVF = _COEF_II - _COEF_I / 2
_COEF_TIRA = 0.40


def _trazo_desde_mv(
    valores_mv: list[float],
    *,
    y0_mm: float,
    x_referencia_mm: float,
    escala_mm: float = _ESCALA_MM_REAL,
    frecuencia: int = FRECUENCIA_HZ,
) -> tuple[tuple[float, float], ...]:
    return tuple(
        (x_referencia_mm + mv * escala_mm, y0_mm + indice / frecuencia * MM_POR_S)
        for indice, mv in enumerate(valores_mv)
    )


def _pulso(
    y0_mm: float, x_referencia_mm: float, *, escala_mm: float = _ESCALA_MM_REAL
) -> tuple[tuple[float, float], ...]:
    """Pie -> meseta -> pie, como mide el ECG real (nunca un escalón que se
    sostiene hasta el final)."""
    valores = [0.0] * 5 + [1.0] * 50 + [0.0] * 5
    return _trazo_desde_mv(valores, y0_mm=y0_mm, x_referencia_mm=x_referencia_mm, escala_mm=escala_mm)


def _onda_seno(n: int, amplitud_mv: float = 0.5) -> list[float]:
    return [amplitud_mv * math.sin(2 * math.pi * 3 * i / n) for i in range(n)]


def _tira_valor(indice_global: int, coeficiente: float) -> float:
    """Mismo generador que `_onda_seno`, pero indexado por posición GLOBAL
    dentro de la tira de 10 s -- permite que la V1 de la grilla (una
    ventana de 2,5 s) coincida EXACTO con su segmento equivalente de la
    tira, como en el ECG real."""
    return coeficiente * math.sin(2 * math.pi * 3 * indice_global / MUESTRAS_TIRA)


def _tira_completa(coeficiente: float) -> list[float]:
    return [_tira_valor(i, coeficiente) for i in range(MUESTRAS_TIRA)]


def _v1_de_grilla(coeficiente: float) -> list[float]:
    inicio = OFFSETS_COLUMNA[2]
    return [_tira_valor(inicio + i, coeficiente) for i in range(MUESTRAS_DERIVACION)]


# (columna, fila) -> coeficiente, para las celdas con relación fisiológica
# real (Einthoven en columna 0, Goldberger en columna 1); el resto (V2..V6)
# no tiene relación que validar, cualquier forma sirve.
_COEFICIENTE_POR_CELDA = {
    (0, 0): _COEF_I,
    (0, 1): _COEF_II,
    (0, 2): _COEF_III,
    (1, 0): _COEF_AVR,
    (1, 1): _COEF_AVL,
    (1, 2): _COEF_AVF,
}


def _corpus_valido(*, escala_mm: float = _ESCALA_MM_REAL) -> tuple[tuple[tuple[float, float], ...], ...]:
    """17 trazos: 12 derivaciones + 1 tira + 4 pulsos (uno por banda: 3
    filas + la banda de la tira), en grilla válida y fisiológicamente
    consistente (Einthoven/Goldberger/V1-vs-tira, ver
    `_validar_fisiologia`)."""
    trazos: list[tuple[tuple[float, float], ...]] = []
    for columna in range(4):
        for fila in range(3):
            if columna == 2 and fila == 0:
                valores = _v1_de_grilla(_COEF_TIRA)
            elif (columna, fila) in _COEFICIENTE_POR_CELDA:
                valores = _onda_seno(MUESTRAS_DERIVACION, amplitud_mv=_COEFICIENTE_POR_CELDA[(columna, fila)])
            else:
                valores = _onda_seno(MUESTRAS_DERIVACION, amplitud_mv=0.15 + 0.05 * fila)
            trazos.append(
                _trazo_desde_mv(
                    valores, y0_mm=_Y_COLUMNA[columna], x_referencia_mm=_X_FILA[fila], escala_mm=escala_mm
                )
            )
    trazos.append(
        _trazo_desde_mv(_tira_completa(_COEF_TIRA), y0_mm=0.0, x_referencia_mm=_X_TIRA, escala_mm=escala_mm)
    )
    for x_referencia in (*_X_FILA, _X_TIRA):
        trazos.append(_pulso(_Y_PULSO, x_referencia, escala_mm=escala_mm))
    return tuple(trazos)


def test_construir_senal_recupera_oraculo_equiespaciado() -> None:
    senal = construir_senal(_corpus_valido())

    assert senal is not None
    assert senal.muestras_uv.shape == (12, 5000)
    assert senal.mascara.shape == (12, 5000)
    indice_v1 = ORDEN_DERIVACIONES.index("V1")
    assert senal.mascara.all(axis=1)[indice_v1]  # tira: fila completa

    # error <= 0.01 mV (10 uV) contra el oráculo, criterio de éxito de la propuesta.
    # V1 se salta acá: su fila la reemplaza por completo la tira de ritmo.
    for columna in range(4):
        for fila in range(3):
            indice_lead = columna * 3 + fila
            if indice_lead == indice_v1:
                continue
            if columna == 2 and fila == 0:
                esperado_mv = _v1_de_grilla(_COEF_TIRA)
            elif (columna, fila) in _COEFICIENTE_POR_CELDA:
                esperado_mv = _onda_seno(MUESTRAS_DERIVACION, amplitud_mv=_COEFICIENTE_POR_CELDA[(columna, fila)])
            else:
                esperado_mv = _onda_seno(MUESTRAS_DERIVACION, amplitud_mv=0.15 + 0.05 * fila)
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
        (_X_FILA[0] + valores[min(i, len(valores) - 1)] * _ESCALA_MM_REAL, _Y_COLUMNA[0] + t * MM_POR_S)
        for i, t in enumerate(tiempos_no_uniformes)
    )

    trazos = list(_corpus_valido())
    trazos[0] = trazo_no_equiespaciado  # columna 0, fila 0
    senal = construir_senal(tuple(trazos))

    assert senal is not None
    recuperado_mv = senal.muestras_uv[0, 0:MUESTRAS_DERIVACION] / 1000.0
    error_maximo = np.max(np.abs(recuperado_mv - np.array(valores[: len(recuperado_mv)])))
    assert error_maximo <= 0.07  # tolerancia algo mayor: remuestreo desde grilla irregular


def test_construir_senal_sigue_la_direccion_del_pulso_invertido() -> None:
    """Todo el corpus con la dirección al revés (+1 mV = +10 mm): el
    resultado tiene que seguir siendo correcto -- la dirección se lee del
    pulso, nunca de una constante fija en el código."""
    senal = construir_senal(_corpus_valido(escala_mm=10.0))

    assert senal is not None
    recuperado_mv = senal.muestras_uv[0, 0:MUESTRAS_DERIVACION] / 1000.0
    esperado_mv = np.array(_onda_seno(MUESTRAS_DERIVACION, amplitud_mv=0.3))
    assert np.max(np.abs(recuperado_mv - esperado_mv)) <= 0.01


def test_construir_senal_falla_si_los_pulsos_apuntan_en_direcciones_distintas() -> None:
    """Calibración inconsistente entre bandas -- ninguna dirección es
    'la correcta' por defecto, así que ante la duda: `None`."""
    trazos = list(_corpus_valido())
    trazos[-1] = _pulso(_Y_PULSO, _X_TIRA, escala_mm=10.0)  # la banda de la tira, al revés que las demás

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_dos_pulsos_compiten_por_la_misma_banda() -> None:
    """Dos pulsos a la misma distancia de una banda (acá: literalmente en
    la misma posición) -- `_emparejar_por_proximidad` no puede resolver una
    asignación 1 a 1, y otra banda se queda sin pulso. Violación de layout:
    `None`, nunca una asignación arbitraria."""
    trazos = list(_corpus_valido())
    trazos[14] = _pulso(_Y_PULSO, _X_FILA[0])  # pulso de la fila 1 duplicado sobre la fila 0

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_ignora_el_orden_de_los_puntos_del_pulso() -> None:
    """El pulso decide pie/meseta por posición temporal (Y), no por el
    orden en que `get_drawings()` entrega los puntos."""
    trazos = list(_corpus_valido())
    pulso_desordenado = tuple(sorted(trazos[-1], key=lambda punto: punto[0]))  # mezclado por X, no por Y
    trazos[-1] = pulso_desordenado

    senal = construir_senal(tuple(trazos))

    assert senal is not None


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
    trazos.append(_trazo_desde_mv(_onda_seno(MUESTRAS_TIRA), y0_mm=0.0, x_referencia_mm=_X_FILA[1]))

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_el_pulso_no_mide_10mm() -> None:
    trazos = list(_corpus_valido())
    valores_20mm = [0.0] * 5 + [2.0] * 50 + [0.0] * 5  # 20mm, no 10mm
    trazos[-1] = _trazo_desde_mv(valores_20mm, y0_mm=_Y_PULSO, x_referencia_mm=_X_TIRA)

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_si_dos_derivaciones_caen_en_la_misma_celda() -> None:
    """Filas no disjuntas: dos trazos con el mismo Y de inicio y mismo X
    de referencia -- viola la grilla 4x3."""
    trazos = list(_corpus_valido())
    trazos[1] = _trazo_desde_mv(_onda_seno(MUESTRAS_DERIVACION), y0_mm=_Y_COLUMNA[0], x_referencia_mm=_X_FILA[0])

    assert construir_senal(tuple(trazos)) is None


def test_construir_senal_falla_ante_trazo_de_longitud_no_reconocida() -> None:
    trazos = list(_corpus_valido())
    trazos[-1] = tuple((0.0, float(i)) for i in range(300))  # ni pulso, ni derivación, ni tira

    assert construir_senal(tuple(trazos)) is None


# --- rechazo de amplitud fuera de rango int16 (CRÍTICO, revisión adversarial) --
#
# Aisladas en `_muestrear` (no vía `construir_senal`): una excursión de
# ~32,8 mV corresponde a ~328 mm de desplazamiento en X, que rompe el
# agrupamiento por banda de amplitud de `_asignar_derivaciones` (el outlier
# ya no cae en el cluster de su fila) -- confundiría "rechazado por rango"
# con "rechazado por geometría de grilla", dos causas distintas. El oráculo
# es el valor conocido a mano (mV objetivo), no la misma fórmula que
# `_muestrear` usa para convertir -- se fija el resultado exacto esperado.


def test_muestrear_rechaza_excursion_que_desborda_int16_en_silencio() -> None:
    """Antes del fix: `.astype(np.int16)` envolvía 32768 uV -> -32768 uV sin
    avisar. Ahora debe rechazar (`None`), nunca recortar ni envolver."""
    amplitud_mv_fuera_de_rango = (AMPLITUD_MAXIMA_UV + 1) / 1000  # 32,768 mV -> 32768 uV
    trazo = _trazo_desde_mv(
        [amplitud_mv_fuera_de_rango] * MUESTRAS_DERIVACION, y0_mm=0.0, x_referencia_mm=0.0
    )

    assert _muestrear(trazo, MUESTRAS_DERIVACION, x_pie=0.0, escala_mm=_ESCALA_MM_REAL) is None


def test_muestrear_rechaza_valores_no_finitos_por_division_cero_sobre_cero() -> None:
    """`escala_mm=0.0` con un trazo cuyo X ya coincide con `x_pie` (violación
    de layout que no debería llegar acá, pero se cubre defensivamente)
    produce `mv = (xs - x_pie) / 0.0 = 0.0 / 0.0 = nan` en TODOS los puntos.
    Antes del guard `~np.isfinite`: `np.round(nan * 1000).astype(np.int16)`
    convierte `nan` a `0` EN SILENCIO (verificado: no lanza, no queda fuera
    de rango) -- pasaría el chequeo de amplitud existente y devolvería una
    señal plana de ceros, corrupción indistinguible de "sin señal real",
    en vez de rechazar explícitamente. `escala_mm=0.0` en `_trazo_desde_mv`
    hace que X sea constante e igual a `x_referencia_mm=0.0` -- coincide con
    `x_pie=0.0` pasado a `_muestrear`, dando `0/0`, no `x/0`."""
    trazo = _trazo_desde_mv(
        [1.0] * MUESTRAS_DERIVACION, y0_mm=0.0, x_referencia_mm=0.0, escala_mm=0.0
    )

    assert _muestrear(trazo, MUESTRAS_DERIVACION, x_pie=0.0, escala_mm=0.0) is None


def test_muestrear_conserva_excursion_exacta_en_el_borde_representable() -> None:
    """32,767 mV (= 32767 uV, el máximo que entra en int16) se conserva
    exacto -- el rechazo empieza estrictamente después del borde, no antes."""
    amplitud_mv_en_el_borde = AMPLITUD_MAXIMA_UV / 1000  # 32,767 mV -> 32767 uV
    trazo = _trazo_desde_mv(
        [amplitud_mv_en_el_borde] * MUESTRAS_DERIVACION, y0_mm=0.0, x_referencia_mm=0.0
    )

    muestras = _muestrear(trazo, MUESTRAS_DERIVACION, x_pie=0.0, escala_mm=_ESCALA_MM_REAL)

    assert muestras is not None
    assert np.all(muestras == AMPLITUD_MAXIMA_UV)
