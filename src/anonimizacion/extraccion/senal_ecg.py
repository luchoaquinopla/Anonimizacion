"""Reconstrucción de la señal de ECG a partir de trazos vectoriales.

Puro numpy (design.md, sección "Algoritmo"): nunca lee texto ni abre un
PDF -- opera sólo sobre los puntos en mm que entrega `trazos_pymupdf.py`
(ya en el espacio sin rotar, ver ese módulo). Validación estricta todo-o-
nada: cualquier violación de layout devuelve `None` -- el ECG se publica
incompleto (`reconciliacion/ecg_mortara.py` agrega `ecg.senal` a
`campos_no_extraidos`), nunca una señal parcial o dudosa.

Geometría esperada (17 trazos negros, medida contra el ECG real): 12
derivaciones de ~1238 puntos en una grilla de 4 columnas (ventana temporal,
por Y de inicio: 0/2,5/5/7,5 s) x 3 filas (banda de amplitud, por X
promedio) -- orden `ORDEN_DERIVACIONES`; 1 tira de ritmo V1 de ~5000 puntos
(los 10 s completos, remplaza el segmento de V1 en la grilla); 4 pulsos de
calibración de ~60 puntos que deben medir 10 mm (1 mV) sin leer el texto de
"N mm/mV" -- si el gain real fuera otro, el pulso mide otra altura y la
calibración falla acá, geométricamente.
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
MM_POR_MV = 10.0  # escala de amplitud nominal del papel
TOLERANCIA_CALIBRACION = 0.02  # ±2%
ORDEN_DERIVACIONES = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
INDICE_TIRA_RITMO = ORDEN_DERIVACIONES.index("V1")


def construir_senal(trazos: tuple[Trazo, ...]) -> SenalEcg | None:
    """`None` si el layout no valida contra la geometría esperada."""
    clasificacion = _clasificar(trazos)
    if clasificacion is None:
        return None
    pulsos, derivaciones, tira = clasificacion

    if not _calibracion_valida(pulsos):
        return None

    asignacion = _asignar_derivaciones(derivaciones)
    if asignacion is None:
        return None

    matriz = np.zeros((12, MUESTRAS_TIRA), dtype=np.int16)
    mascara = np.zeros((12, MUESTRAS_TIRA), dtype=bool)

    for indice_lead, trazo in asignacion.items():
        muestras = _muestrear(trazo, MUESTRAS_DERIVACION)
        if muestras is None:
            return None
        columna = indice_lead // 3
        inicio = OFFSETS_COLUMNA[columna]
        matriz[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] = muestras
        mascara[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] = True

    muestras_tira = _muestrear(tira, MUESTRAS_TIRA)
    if muestras_tira is None:
        return None
    matriz[INDICE_TIRA_RITMO, :] = muestras_tira
    mascara[INDICE_TIRA_RITMO, :] = True

    return SenalEcg(muestras_uv=matriz, mascara=mascara)


def _clasificar(
    trazos: tuple[Trazo, ...],
) -> tuple[list[Trazo], list[Trazo], Trazo] | None:
    """Separa los trazos por cantidad de puntos: pulso de calibración
    (~60), derivación de la grilla (~1238) o tira de ritmo (~5000).
    Cualquier trazo que no calce en ninguna categoría es una violación de
    layout -- `None`."""
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


def _calibracion_valida(pulsos: list[Trazo]) -> bool:
    """Cada pulso debe medir `MM_POR_MV` (10 mm = 1 mV) desde su pie
    (primer punto) -- geométrico, nunca lee "N mm/mV" del texto."""
    for pulso in pulsos:
        base_x = pulso[0][0]
        altura_mm = max(abs(x - base_x) for x, _y in pulso)
        if abs(altura_mm - MM_POR_MV) / MM_POR_MV > TOLERANCIA_CALIBRACION:
            return False
    return True


def _asignar_derivaciones(derivaciones: list[Trazo]) -> dict[int, Trazo] | None:
    """Agrupa por columna (Y de inicio -> ventana temporal) y por fila (X
    promedio -> banda de amplitud), design.md paso "Asignación". `None` si
    no quedan exactamente 4x3 celdas disjuntas (violación de layout)."""
    inicios_y = [trazo[0][1] for trazo in derivaciones]
    centros_x = [sum(x for x, _y in trazo) / len(trazo) for trazo in derivaciones]

    columnas = _particionar(inicios_y, 4)
    filas = _particionar(centros_x, 3)
    if columnas is None or filas is None:
        return None

    asignacion: dict[int, Trazo] = {}
    for indice_derivacion, trazo in enumerate(derivaciones):
        indice_lead = columnas[indice_derivacion] * 3 + filas[indice_derivacion]
        if indice_lead in asignacion:
            return None  # dos derivaciones en la misma celda: filas no disjuntas
        asignacion[indice_lead] = trazo

    if len(asignacion) != 12:
        return None
    return asignacion


def _particionar(valores: list[float], grupos: int) -> list[int] | None:
    """Asigna a cada valor un índice de grupo 0..`grupos`-1, ordenando y
    partiendo por los `grupos - 1` huecos más grandes entre valores
    consecutivos. `None` si no resultan exactamente `grupos` clusters
    (p. ej. valores demasiado parejos, sin huecos claros)."""
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


def _muestrear(trazo: Trazo, cantidad: int) -> np.ndarray | None:
    """Reconstruye `cantidad` muestras uniformes a `FRECUENCIA_HZ` en µV a
    partir de los puntos (mm) del trazo. Siempre interpola (idempotente si
    ya estaban equiespaciados, design.md: desvío > 1% dispara interpolar)
    para no bifurcar el código por ese caso."""
    ordenados = sorted(trazo, key=lambda punto: punto[1])
    ys = np.array([y for _x, y in ordenados], dtype=float)
    xs = np.array([x for x, _y in ordenados], dtype=float)
    if len(set(ys)) < 2:
        return None

    tiempos_s = (ys - ys[0]) / MM_POR_S
    # línea base = centro de la banda de amplitud (promedio de X), NO el
    # primer punto: a diferencia de un pulso de calibración (que sí arranca
    # en su "pie"), una derivación puede empezar en cualquier fase de la
    # onda -- el primer punto no es un cero confiable.
    mv = (xs - xs.mean()) / MM_POR_MV

    duracion_objetivo = (cantidad - 1) / FRECUENCIA_HZ
    if tiempos_s[-1] < duracion_objetivo * (1 - TOLERANCIA_CALIBRACION):
        return None  # el trazo no cubre la ventana temporal esperada

    grilla_s = np.linspace(0, duracion_objetivo, cantidad)
    mv_interpolado = np.interp(grilla_s, tiempos_s, mv)
    return np.round(mv_interpolado * 1000).astype(np.int16)
