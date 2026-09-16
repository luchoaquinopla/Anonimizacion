"""Reconstrucción de la señal de ECG a partir de trazos vectoriales.
Puro numpy; validación estricta todo-o-nada: cualquier violación de layout devuelve `None`.

Geometría esperada, medida contra el ECG real: 12 derivaciones (~1238 puntos, 4 columnas x
3 filas), 1 tira de ritmo V1 (~5000 puntos), 4 pulsos de calibración (~60 puntos). El signo y
la línea base de cada banda se leen del pulso de su banda, nunca de una constante fija: +1 mV
se mide como -10 mm en X (pie a la derecha, meseta a la izquierda). La dirección del tiempo se
deriva de la posición de los pulsos (siempre marcan el inicio), nunca se asume Y creciente =
tiempo creciente. Invariante: «Calibración del trazado del ECG» (Obsidian, Invariantes medidos).
"""

from __future__ import annotations

import numpy as np

from ..dominio.senal_ecg import SenalEcg
from .trazos_pymupdf import Trazo

FRECUENCIA_HZ = 500
MUESTRAS_DERIVACION = 1238
MUESTRAS_TIRA = 5000
TOLERANCIA_MUESTRAS = 2
OFFSETS_COLUMNA = (0, 1250, 2500, 3750)
MM_POR_S = 25.0  # escala de tiempo del papel
MM_POR_MV = 10.0  # escala de amplitud NOMINAL esperada -- valida cada pulso, no convierte
TOLERANCIA_CALIBRACION = 0.02  # ±2%, altura del pulso vs MM_POR_MV
TOLERANCIA_DURACION = 0.02  # ±2%, cobertura temporal del trazo vs la ventana esperada
AMPLITUD_MAXIMA_UV = 32767  # tope representable en int16 (µV)
ORDEN_DERIVACIONES = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
INDICE_TIRA_RITMO = ORDEN_DERIVACIONES.index("V1")
_INDICE_REFERENCIA_TIRA = 3  # dentro de `referencias_x`: 0..2 = filas de la grilla, 3 = tira
VERSION_EXTRACTOR = 2  # v1 tenía la orientación del tiempo invertida

# Residuo Einthoven/Goldberger medido contra el ECG real ~4-5% del RMS; margen amplio (20%)
# porque el objetivo es detectar una asignación de columna/fila cruzada, no exigir calidad de
# laboratorio. Invariante: «Calibración del trazado del ECG» (Obsidian, Invariantes medidos).
UMBRAL_RESIDUO_EINTHOVEN = 0.20
UMBRAL_RESIDUO_GOLDBERGER = 0.20
# Correlación V1-grilla vs V1-tira medida en el ECG real: r=1,000; 0.8 deja margen amplio.
UMBRAL_CORRELACION_V1 = 0.8


def construir_senal(trazos: tuple[Trazo, ...]) -> SenalEcg | None:
    """`None` si el layout no valida, la dirección del tiempo es ambigua, o falla la fisiología."""
    clasificacion = _clasificar(trazos)
    if clasificacion is None:
        return None
    pulsos, derivaciones, tira = clasificacion

    direccion, y_pulsos_promedio = _direccion_y_referencia_pulsos(pulsos, derivaciones, tira)
    if direccion is None:
        return None

    asignacion_grilla, centroides_fila = _asignar_derivaciones(derivaciones, direccion, y_pulsos_promedio)
    if asignacion_grilla is None:
        return None

    centro_x_tira = sum(x for x, _y in tira) / len(tira)
    referencias_x = (*centroides_fila, centro_x_tira)

    calibracion_por_referencia = _calibrar_pulsos(pulsos, referencias_x)
    if calibracion_por_referencia is None:
        return None

    matriz = np.zeros((12, MUESTRAS_TIRA), dtype=np.int16)
    mascara = np.zeros((12, MUESTRAS_TIRA), dtype=bool)
    muestras_grilla_v1: tuple[int, np.ndarray] | None = None

    for indice_lead, trazo in asignacion_grilla.items():
        fila = indice_lead % 3
        x_pie, escala_mm = calibracion_por_referencia[fila]
        muestras = _muestrear(trazo, MUESTRAS_DERIVACION, x_pie=x_pie, escala_mm=escala_mm, direccion=direccion)
        if muestras is None:
            return None
        columna = indice_lead // 3
        inicio = OFFSETS_COLUMNA[columna]
        matriz[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] = muestras
        mascara[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] = True
        if indice_lead == INDICE_TIRA_RITMO:
            # se sobrescribe más abajo con la tira -- se guarda para validar
            # contra ella ANTES de descartarla (ver `_validar_fisiologia`)
            muestras_grilla_v1 = (inicio, muestras)

    x_pie_tira, escala_tira = calibracion_por_referencia[_INDICE_REFERENCIA_TIRA]
    muestras_tira = _muestrear(tira, MUESTRAS_TIRA, x_pie=x_pie_tira, escala_mm=escala_tira, direccion=direccion)
    if muestras_tira is None:
        return None

    if not _validar_fisiologia(matriz, muestras_grilla_v1, muestras_tira):
        return None

    matriz[INDICE_TIRA_RITMO, :] = muestras_tira
    mascara[INDICE_TIRA_RITMO, :] = True

    return SenalEcg(muestras_uv=matriz, mascara=mascara, version_extractor=VERSION_EXTRACTOR)


def _direccion_y_referencia_pulsos(
    pulsos: list[Trazo], derivaciones: list[Trazo], tira: Trazo
) -> tuple[int | None, float]:
    """`+1`/`-1` según hacia dónde avanza el tiempo (los pulsos marcan el inicio); `None` si es ambiguo."""
    y_pulsos = [y for pulso in pulsos for _x, y in pulso]
    y_pulsos_promedio = sum(y_pulsos) / len(y_pulsos)

    y_trazas = [y for trazo in (*derivaciones, tira) for _x, y in trazo]
    y_minimo, y_maximo = min(y_trazas), max(y_trazas)

    if y_pulsos_promedio > y_maximo:
        return -1, y_pulsos_promedio
    if y_pulsos_promedio < y_minimo:
        return 1, y_pulsos_promedio
    return None, y_pulsos_promedio


def _clasificar(
    trazos: tuple[Trazo, ...],
) -> tuple[list[Trazo], list[Trazo], Trazo] | None:
    """Separa los trazos por cantidad de puntos: pulso (~60), derivación (~1238) o tira (~5000)."""
    pulsos: list[Trazo] = []
    derivaciones: list[Trazo] = []
    tiras: list[Trazo] = []
    for trazo in trazos:
        n = len(trazo)
        if abs(n - MUESTRAS_DERIVACION) <= TOLERANCIA_MUESTRAS:
            derivaciones.append(trazo)
        elif abs(n - MUESTRAS_TIRA) <= TOLERANCIA_MUESTRAS:
            tiras.append(trazo)
        elif n <= 100:
            pulsos.append(trazo)
        else:
            return None

    if len(pulsos) != 4 or len(derivaciones) != 12 or len(tiras) != 1:
        return None
    return pulsos, derivaciones, tiras[0]


def _asignar_derivaciones(
    derivaciones: list[Trazo], direccion: int, y_pulsos_promedio: float
) -> tuple[dict[int, Trazo], tuple[float, float, float]] | tuple[None, None]:
    """Agrupa por columna (centroide de Y) y por fila (X promedio -> banda de amplitud).
    `(None, None)` si no quedan exactamente 4x3 celdas disjuntas."""
    centros_y = [sum(y for _x, y in trazo) / len(trazo) for trazo in derivaciones]
    centros_x = [sum(x for x, _y in trazo) / len(trazo) for trazo in derivaciones]

    grupos_y = _particionar(centros_y, 4)
    filas = _particionar(centros_x, 3)
    if grupos_y is None or filas is None:
        return None, None

    # Extremo de cada trazo más cercano a los pulsos: Y máximo o mínimo según la dirección.
    extremos_por_grupo: dict[int, list[float]] = {}
    for grupo, trazo in zip(grupos_y, derivaciones):
        ys = [y for _x, y in trazo]
        extremo = max(ys) if direccion == -1 else min(ys)
        extremos_por_grupo.setdefault(grupo, []).append(extremo)

    distancia_por_grupo = {
        grupo: abs(y_pulsos_promedio - sum(valores) / len(valores))
        for grupo, valores in extremos_por_grupo.items()
    }
    orden_columnas = sorted(distancia_por_grupo, key=lambda grupo: distancia_por_grupo[grupo])
    if len(orden_columnas) != 4:
        return None, None
    columna_real = {grupo_arbitrario: indice for indice, grupo_arbitrario in enumerate(orden_columnas)}

    asignacion: dict[int, Trazo] = {}
    suma_por_fila = [0.0, 0.0, 0.0]
    cuenta_por_fila = [0, 0, 0]
    for indice_derivacion, trazo in enumerate(derivaciones):
        fila = filas[indice_derivacion]
        columna = columna_real[grupos_y[indice_derivacion]]
        indice_lead = columna * 3 + fila
        if indice_lead in asignacion:
            return None, None  # dos derivaciones en la misma celda: filas no disjuntas
        asignacion[indice_lead] = trazo
        suma_por_fila[fila] += centros_x[indice_derivacion]
        cuenta_por_fila[fila] += 1

    if len(asignacion) != 12 or any(cuenta == 0 for cuenta in cuenta_por_fila):
        return None, None

    centroides_fila = tuple(suma / cuenta for suma, cuenta in zip(suma_por_fila, cuenta_por_fila))
    return asignacion, centroides_fila


def _particionar(valores: list[float], grupos: int) -> list[int] | None:
    """Asigna grupo 0..`grupos`-1 partiendo por los huecos más grandes. `None` si no hay `grupos` clusters."""
    orden = sorted(range(len(valores)), key=lambda i: valores[i])
    ordenados = [valores[i] for i in orden]

    huecos = sorted(
        (ordenados[i + 1] - ordenados[i], i) for i in range(len(ordenados) - 1)
    )
    cortes = sorted(indice for _hueco, indice in huecos[-(grupos - 1) :]) if grupos > 1 else []
    if len(cortes) != grupos - 1:
        return None

    grupo_por_posicion: list[int] = []
    grupo_actual = 0
    for posicion in range(len(ordenados)):
        if grupo_actual < len(cortes) and posicion > cortes[grupo_actual]:
            grupo_actual += 1
        grupo_por_posicion.append(grupo_actual)
    if grupo_actual != grupos - 1:
        return None

    resultado = [0] * len(valores)
    for posicion, indice_original in enumerate(orden):
        resultado[indice_original] = grupo_por_posicion[posicion]
    return resultado


def _pie_y_meseta(pulso: Trazo) -> tuple[float, float]:
    """`(x_pie, x_meseta)` de un pulso cuadrado pie -> meseta -> pie.
    `x_meseta` es el punto de máxima desviación respecto de `x_pie`."""
    ordenados = sorted(pulso, key=lambda punto: punto[1])
    xs = [x for x, _y in ordenados]
    x_pie = xs[0]
    indice_extremo = max(range(len(xs)), key=lambda i: abs(xs[i] - x_pie))
    return x_pie, xs[indice_extremo]


def _calibrar_pulsos(
    pulsos: list[Trazo], referencias_x: tuple[float, ...]
) -> dict[int, tuple[float, float]] | None:
    """Valida los 4 pulsos y los empareja con su banda de amplitud (`referencias_x`).
    `None` si la altura, la dirección pie->meseta, o el emparejamiento 1 a 1 no cierran."""
    calibraciones: list[tuple[float, float]] = []
    direcciones_positivas: set[bool] = set()
    for pulso in pulsos:
        x_pie, x_meseta = _pie_y_meseta(pulso)
        escala_mm = x_meseta - x_pie
        if abs(abs(escala_mm) - MM_POR_MV) / MM_POR_MV > TOLERANCIA_CALIBRACION:
            return None
        direcciones_positivas.add(escala_mm > 0)
        calibraciones.append((x_pie, escala_mm))

    if len(direcciones_positivas) != 1:
        return None  # pulsos con direcciones pie->meseta distintas entre sí

    indices_referencia = _emparejar_por_proximidad(
        [x_pie for x_pie, _escala in calibraciones], list(referencias_x)
    )
    if indices_referencia is None:
        return None

    return {
        indice_referencia: calibraciones[indice_pulso]
        for indice_pulso, indice_referencia in enumerate(indices_referencia)
    }


def _emparejar_por_proximidad(valores: list[float], referencias: list[float]) -> list[int] | None:
    """Empareja cada valor con el índice de la referencia más cercana. `None` si no es 1 a 1."""
    asignacion = [min(range(len(referencias)), key=lambda i: abs(v - referencias[i])) for v in valores]
    if len(set(asignacion)) != len(referencias):
        return None
    return asignacion


def _muestrear(
    trazo: Trazo, cantidad: int, *, x_pie: float, escala_mm: float, direccion: int = 1
) -> np.ndarray | None:
    """Reconstruye `cantidad` muestras uniformes a `FRECUENCIA_HZ` en µV, calibrado con `(x_pie, escala_mm)`.
    `direccion` (`+1`/`-1`): el primer punto en el tiempo es el de Y mínima o máxima."""
    ordenados = sorted(trazo, key=lambda punto: direccion * punto[1])
    ys = np.array([y for _x, y in ordenados], dtype=float)
    xs = np.array([x for x, _y in ordenados], dtype=float)
    if len(set(ys)) < 2:
        return None

    tiempos_s = direccion * (ys - ys[0]) / MM_POR_S
    mv = (xs - x_pie) / escala_mm

    duracion_objetivo = (cantidad - 1) / FRECUENCIA_HZ
    cobertura = tiempos_s[-1] / duracion_objetivo
    if abs(cobertura - 1.0) > TOLERANCIA_DURACION:
        # Rechaza tanto sub- como sobre-cobertura: ambas violan el layout esperado por igual.
        return None

    grilla_s = np.linspace(0, duracion_objetivo, cantidad)
    mv_interpolado = np.interp(grilla_s, tiempos_s, mv)
    # escala_mm=0.0 produce nan/inf; nan.astype(int16) da 0 en silencio, indistinguible de "sin señal".
    if not np.all(np.isfinite(mv_interpolado)):
        return None
    # .astype(int16) envuelve en silencio fuera de rango (32768 -> -32768): se valida antes.
    muestras_uv = np.round(mv_interpolado * 1000)
    if np.any(np.abs(muestras_uv) > AMPLITUD_MAXIMA_UV):
        return None
    return muestras_uv.astype(np.int16)


def _validar_fisiologia(
    matriz: np.ndarray, muestras_grilla_v1: tuple[int, np.ndarray] | None, muestras_tira: np.ndarray
) -> bool:
    """Última barrera: verifica Einthoven y Goldberger, y que V1 de la grilla calce con la tira.
    Cualquier residuo por fuera de umbral -- `False`, la señal se descarta completa."""
    indice = {derivacion: i for i, derivacion in enumerate(ORDEN_DERIVACIONES)}

    ventana_miembros = slice(OFFSETS_COLUMNA[0], OFFSETS_COLUMNA[0] + MUESTRAS_DERIVACION)
    i = matriz[indice["I"], ventana_miembros].astype(float)
    ii = matriz[indice["II"], ventana_miembros].astype(float)
    iii = matriz[indice["III"], ventana_miembros].astype(float)
    rms_ii = np.sqrt(np.mean(ii**2))
    if rms_ii == 0:
        return False
    residuo_einthoven = np.sqrt(np.mean((ii - (i + iii)) ** 2))
    if residuo_einthoven / rms_ii > UMBRAL_RESIDUO_EINTHOVEN:
        return False

    ventana_aumentada = slice(OFFSETS_COLUMNA[1], OFFSETS_COLUMNA[1] + MUESTRAS_DERIVACION)
    avr = matriz[indice["aVR"], ventana_aumentada].astype(float)
    avl = matriz[indice["aVL"], ventana_aumentada].astype(float)
    avf = matriz[indice["aVF"], ventana_aumentada].astype(float)
    rms_aumentadas = np.sqrt(np.mean(np.concatenate([avr, avl, avf]) ** 2))
    if rms_aumentadas == 0:
        return False
    residuo_goldberger = np.sqrt(np.mean((avr + avl + avf) ** 2))
    if residuo_goldberger / rms_aumentadas > UMBRAL_RESIDUO_GOLDBERGER:
        return False

    if muestras_grilla_v1 is not None:
        inicio, grilla_v1 = muestras_grilla_v1
        grilla_v1 = grilla_v1.astype(float)
        ventana_tira = muestras_tira[inicio : inicio + MUESTRAS_DERIVACION].astype(float)
        if np.std(grilla_v1) == 0 or np.std(ventana_tira) == 0:
            return False
        correlacion = np.corrcoef(grilla_v1, ventana_tira)[0, 1]
        if correlacion < UMBRAL_CORRELACION_V1:
            return False

    return True
