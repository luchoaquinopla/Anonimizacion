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
calibración de ~60 puntos, uno por banda de amplitud (las 3 filas de la
grilla + la propia banda de la tira), medidos justo después de la última
columna.

Signo y línea base (hallazgo contra el ECG real, no un supuesto de texto):
cada pulso es un cuadrado pie -> meseta -> pie; +1 mV se mide, en el PDF
real, como un desplazamiento de -10 mm en X (pie a la DERECHA, meseta a la
IZQUIERDA) -- lo contrario de "más mV = más X". Por eso el signo y la línea
base de cada banda de amplitud se leen SIEMPRE del pulso de esa banda
(`x_pie`, `escala_mm = x_meseta - x_pie`), nunca de una constante de signo
ni del promedio del propio trazo de la derivación (que no es un cero
confiable: una derivación puede tener ST elevado, por ejemplo). Si los 4
pulsos no apuntan en la misma dirección, la calibración es inconsistente y
la señal se descarta.
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
TOLERANCIA_DURACION = 0.02  # ±2%, cobertura temporal del trazo vs la ventana esperada -- se
# separa de TOLERANCIA_CALIBRACION porque mide otra cosa (duración, no altura de pulso) y no
# hay ninguna razón para que ambas tolerancias deban moverse juntas si una se recalibra.
AMPLITUD_MAXIMA_UV = 32767  # tope representable en int16 (µV); ver `_muestrear`, rechazo todo-o-nada
ORDEN_DERIVACIONES = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
INDICE_TIRA_RITMO = ORDEN_DERIVACIONES.index("V1")
_INDICE_REFERENCIA_TIRA = 3  # dentro de `referencias_x`: 0..2 = filas de la grilla, 3 = tira


def construir_senal(trazos: tuple[Trazo, ...]) -> SenalEcg | None:
    """`None` si el layout no valida contra la geometría esperada."""
    clasificacion = _clasificar(trazos)
    if clasificacion is None:
        return None
    pulsos, derivaciones, tira = clasificacion

    asignacion_grilla, centroides_fila = _asignar_derivaciones(derivaciones)
    if asignacion_grilla is None:
        return None

    centro_x_tira = sum(x for x, _y in tira) / len(tira)
    referencias_x = (*centroides_fila, centro_x_tira)

    calibracion_por_referencia = _calibrar_pulsos(pulsos, referencias_x)
    if calibracion_por_referencia is None:
        return None

    matriz = np.zeros((12, MUESTRAS_TIRA), dtype=np.int16)
    mascara = np.zeros((12, MUESTRAS_TIRA), dtype=bool)

    for indice_lead, trazo in asignacion_grilla.items():
        fila = indice_lead % 3
        x_pie, escala_mm = calibracion_por_referencia[fila]
        muestras = _muestrear(trazo, MUESTRAS_DERIVACION, x_pie=x_pie, escala_mm=escala_mm)
        if muestras is None:
            return None
        columna = indice_lead // 3
        inicio = OFFSETS_COLUMNA[columna]
        matriz[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] = muestras
        mascara[indice_lead, inicio : inicio + MUESTRAS_DERIVACION] = True

    x_pie_tira, escala_tira = calibracion_por_referencia[_INDICE_REFERENCIA_TIRA]
    muestras_tira = _muestrear(tira, MUESTRAS_TIRA, x_pie=x_pie_tira, escala_mm=escala_tira)
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


def _asignar_derivaciones(
    derivaciones: list[Trazo],
) -> tuple[dict[int, Trazo], tuple[float, float, float]] | tuple[None, None]:
    """Agrupa por columna (Y de inicio -> ventana temporal) y por fila (X
    promedio -> banda de amplitud), design.md paso "Asignación". Devuelve
    también el centroide de X de cada fila -- lo necesita `_calibrar_pulsos`
    para emparejar cada pulso con su banda. `(None, None)` si no quedan
    exactamente 4x3 celdas disjuntas (violación de layout)."""
    inicios_y = [trazo[0][1] for trazo in derivaciones]
    centros_x = [sum(x for x, _y in trazo) / len(trazo) for trazo in derivaciones]

    columnas = _particionar(inicios_y, 4)
    filas = _particionar(centros_x, 3)
    if columnas is None or filas is None:
        return None, None

    asignacion: dict[int, Trazo] = {}
    suma_por_fila = [0.0, 0.0, 0.0]
    cuenta_por_fila = [0, 0, 0]
    for indice_derivacion, trazo in enumerate(derivaciones):
        fila = filas[indice_derivacion]
        indice_lead = columnas[indice_derivacion] * 3 + fila
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


def _pie_y_meseta(pulso: Trazo) -> tuple[float, float]:
    """`(x_pie, x_meseta)` de un pulso cuadrado pie -> meseta -> pie.

    `x_pie` es el X del primer punto en orden temporal (el pulso siempre
    arranca en reposo, medido). `x_meseta` es el X del punto de máxima
    desviación respecto de `x_pie` -- robusto tanto si el pulso vuelve a
    `x_pie` al final (medido contra el ECG real) como si se sostiene hasta
    el último punto (fixture sintético más simple)."""
    ordenados = sorted(pulso, key=lambda punto: punto[1])
    xs = [x for x, _y in ordenados]
    x_pie = xs[0]
    indice_extremo = max(range(len(xs)), key=lambda i: abs(xs[i] - x_pie))
    return x_pie, xs[indice_extremo]


def _calibrar_pulsos(
    pulsos: list[Trazo], referencias_x: tuple[float, ...]
) -> dict[int, tuple[float, float]] | None:
    """Valida los 4 pulsos y los empareja con su banda de amplitud
    (`referencias_x`: 3 filas de la grilla + la banda de la tira).

    `None` si: la altura de algún pulso no mide `MM_POR_MV` ±
    `TOLERANCIA_CALIBRACION`; la dirección (pie -> meseta) no es la misma en
    los 4 (calibración inconsistente entre bandas -- nunca se asume un
    signo fijo); o el emparejamiento por proximidad con `referencias_x` no
    resulta 1 a 1 (violación de layout)."""
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
    """Empareja cada valor con el índice de la referencia más cercana.
    `None` si no resulta una asignación 1 a 1 (dos valores compitiendo por
    la misma referencia -- violación de layout)."""
    asignacion = [min(range(len(referencias)), key=lambda i: abs(v - referencias[i])) for v in valores]
    if len(set(asignacion)) != len(referencias):
        return None
    return asignacion


def _muestrear(trazo: Trazo, cantidad: int, *, x_pie: float, escala_mm: float) -> np.ndarray | None:
    """Reconstruye `cantidad` muestras uniformes a `FRECUENCIA_HZ` en µV a
    partir de los puntos (mm) del trazo, calibrado con `(x_pie, escala_mm)`
    del pulso de su banda de amplitud (nunca con una constante de signo ni
    con el promedio del propio trazo). Siempre interpola (idempotente si ya
    estaban equiespaciados, design.md: desvío > 1% dispara interpolar) para
    no bifurcar el código por ese caso."""
    ordenados = sorted(trazo, key=lambda punto: punto[1])
    ys = np.array([y for _x, y in ordenados], dtype=float)
    xs = np.array([x for x, _y in ordenados], dtype=float)
    if len(set(ys)) < 2:
        return None

    tiempos_s = (ys - ys[0]) / MM_POR_S
    mv = (xs - x_pie) / escala_mm

    duracion_objetivo = (cantidad - 1) / FRECUENCIA_HZ
    cobertura = tiempos_s[-1] / duracion_objetivo
    if abs(cobertura - 1.0) > TOLERANCIA_DURACION:
        # rechaza tanto sub- como sobre-cobertura: un trazo notablemente más
        # largo que la ventana esperada es tan sospechoso de violar el
        # layout como uno más corto -- ninguna razón para tratarlos distinto
        return None

    grilla_s = np.linspace(0, duracion_objetivo, cantidad)
    mv_interpolado = np.interp(grilla_s, tiempos_s, mv)
    # Guard explícito de no-finitos: `escala_mm=0.0` (u otra violación de
    # calibración que no debería llegar acá) produce `nan`/`inf` en `mv`.
    # `nan.astype(np.int16)` da `0` EN SILENCIO -- pasaría el chequeo de
    # amplitud de abajo y devolvería una señal plana de ceros, corrupción
    # indistinguible de "sin señal real" (ver test
    # `test_muestrear_rechaza_valores_no_finitos_por_division_cero_sobre_cero`).
    # Mismo criterio "todo o nada" que el resto del módulo: rechazar, nunca
    # sanear en silencio.
    if not np.all(np.isfinite(mv_interpolado)):
        return None
    # CRÍTICO (revisión adversarial): `.astype(np.int16)` sobre un valor fuera
    # de rango envuelve en silencio (p. ej. 32768 -> -32768) en vez de
    # lanzar -- corrompería la señal sin ningún aviso. Se valida ANTES de
    # convertir y se rechaza (nunca se recorta: recortar también corrompe en
    # silencio, sólo que de forma distinta) -- mismo criterio "todo o nada"
    # que el resto de este módulo. `np.round` redondea mitad al par
    # (banker's rounding): error ≤ 0,5 µV frente al valor exacto, sin sesgo
    # sistemático hacia arriba/abajo -- aceptable frente a la resolución de
    # 1 µV de la calibración.
    muestras_uv = np.round(mv_interpolado * 1000)
    if np.any(np.abs(muestras_uv) > AMPLITUD_MAXIMA_UV):
        return None
    return muestras_uv.astype(np.int16)
