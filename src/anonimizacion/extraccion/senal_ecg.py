"""Reconstrucción de la señal de ECG a partir de trazos vectoriales.

Puro numpy (design.md, sección "Algoritmo"): nunca lee texto ni abre un
PDF -- opera sólo sobre los puntos en mm que entrega `trazos_pymupdf.py`
(ya en el espacio sin rotar, ver ese módulo). Validación estricta todo-o-
nada: cualquier violación de layout devuelve `None` -- el ECG se publica
incompleto (`reconciliacion/ecg_mortara.py` agrega `ecg.senal` a
`campos_no_extraidos`), nunca una señal parcial o dudosa.

Geometría esperada (17 trazos negros, medida contra el ECG real): 12
derivaciones de ~1238 puntos en una grilla de 4 columnas (ventana temporal
de 2,5 s cada una, agrupadas por centroide de Y y ordenadas por distancia
real a los pulsos de calibración -- ver más abajo, "Dirección del
tiempo") x 3 filas (banda de amplitud, por X promedio) -- orden
`ORDEN_DERIVACIONES`; 1 tira de ritmo V1 de ~5000 puntos (los 10 s
completos, remplaza el segmento de V1 en la grilla); 4 pulsos de
calibración de ~60 puntos, uno por banda de amplitud (las 3 filas de la
grilla + la propia banda de la tira), medidos en el extremo de Y que marca
el INICIO del registro.

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

Dirección del tiempo (CORRECCIÓN CRÍTICA, verificado contra el ECG real):
el eje vertical corre por Y, pero el SENTIDO en que avanza el tiempo NO es
un supuesto fijo del código -- se deriva de la posición de los pulsos de
calibración, que siempre marcan el INICIO del registro (medido: en el PDF
real quedan en el extremo de Y ALTA, más allá de toda derivación). El
tiempo avanza ALEJÁNDOSE de los pulsos. Asumir "Y creciente = tiempo
creciente" sin verificarlo (el bug original) invierte cada derivación en
el tiempo Y cruza las columnas entre sí (la primera columna en el tiempo
es la más CERCANA a los pulsos, no la de Y más chica) -- ver
`_direccion_y_referencia_pulsos` y `_asignar_derivaciones`. Si los pulsos no
quedan claramente más allá de un extremo de las derivaciones, la dirección
es ambigua y la señal se descarta (`None`), nunca se asume una por defecto.

Validación fisiológica (obligatoria, ver `_validar_fisiologia`): una
columna o fila mal asignada puede calibrar perfectamente banda por banda y
seguir siendo una señal cruzada. Antes de aceptar, se verifica Einthoven
(II = I + III) sobre la columna de miembros, Goldberger (aVR+aVL+aVF = 0)
sobre la columna aumentada, y que la V1 de la grilla (que se descarta,
reemplazada por la tira) correlacione con el segmento equivalente de la
tira -- cualquier violación descarta la señal completa.
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
VERSION_EXTRACTOR = 2  # v1 tenía la orientación del tiempo invertida -- ver docstring del módulo

# Umbrales de validación fisiológica (`_validar_fisiologia`): residuo de
# Einthoven/Goldberger medido contra el ECG real ~4-5% del RMS de referencia;
# se deja margen amplio (20%) porque el objetivo es detectar una asignación
# de columna/fila cruzada (residuo grande), no exigir una señal de calidad
# de laboratorio.
UMBRAL_RESIDUO_EINTHOVEN = 0.20
UMBRAL_RESIDUO_GOLDBERGER = 0.20
# Correlación V1-grilla vs V1-tira medida en el ECG real: r=1,000 (misma
# derivación, dos trazos independientes) -- 0.8 deja margen amplio y sigue
# rechazando cualquier desalineación temporal o cruce de columna.
UMBRAL_CORRELACION_V1 = 0.8


def construir_senal(trazos: tuple[Trazo, ...]) -> SenalEcg | None:
    """`None` si el layout no valida contra la geometría esperada, la
    dirección del tiempo es ambigua, o la señal no pasa la validación
    fisiológica (`_validar_fisiologia`)."""
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
    """Deriva el sentido en que avanza el tiempo a partir de la posición de
    los pulsos: SIEMPRE marcan el inicio del registro (medido), así que el
    tiempo avanza alejándose de ellos. `+1` si el tiempo avanza con Y
    creciente (pulsos más allá del Y mínimo de las derivaciones), `-1` si
    avanza con Y decreciente (pulsos más allá del Y máximo). `None` si los
    pulsos no quedan claramente más allá de un extremo (ambiguo -- nunca se
    asume una dirección por defecto)."""
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
    derivaciones: list[Trazo], direccion: int, y_pulsos_promedio: float
) -> tuple[dict[int, Trazo], tuple[float, float, float]] | tuple[None, None]:
    """Agrupa por columna (ventana temporal) y por fila (X promedio -> banda
    de amplitud), design.md paso "Asignación". El agrupamiento por columna
    usa el CENTROIDE de Y (robusto al orden en que `get_drawings()` entrega
    los puntos); el ORDEN temporal real de esas columnas (cuál es la 0,
    ventana 0-2,5s, etc.) se deriva de la distancia de cada columna a los
    pulsos -- SIEMPRE la más cercana es la columna 0 (los pulsos marcan el
    inicio del registro, `direccion` ya viene resuelto por
    `_direccion_y_referencia_pulsos`). Devuelve también el centroide de X de
    cada fila -- lo necesita `_calibrar_pulsos` para emparejar cada pulso con
    su banda. `(None, None)` si no quedan exactamente 4x3 celdas disjuntas
    (violación de layout)."""
    centros_y = [sum(y for _x, y in trazo) / len(trazo) for trazo in derivaciones]
    centros_x = [sum(x for x, _y in trazo) / len(trazo) for trazo in derivaciones]

    grupos_y = _particionar(centros_y, 4)
    filas = _particionar(centros_x, 3)
    if grupos_y is None or filas is None:
        return None, None

    # extremo de cada trazo más cercano a los pulsos (arranque temporal real
    # de esa derivación): Y máximo si el tiempo avanza hacia Y decreciente,
    # Y mínimo si avanza hacia Y creciente.
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


def _muestrear(
    trazo: Trazo, cantidad: int, *, x_pie: float, escala_mm: float, direccion: int = 1
) -> np.ndarray | None:
    """Reconstruye `cantidad` muestras uniformes a `FRECUENCIA_HZ` en µV a
    partir de los puntos (mm) del trazo, calibrado con `(x_pie, escala_mm)`
    del pulso de su banda de amplitud (nunca con una constante de signo ni
    con el promedio del propio trazo). Siempre interpola (idempotente si ya
    estaban equiespaciados, design.md: desvío > 1% dispara interpolar) para
    no bifurcar el código por ese caso.

    `direccion` (`+1`/`-1`, ver `_direccion_y_referencia_pulsos`): el primer
    punto en el tiempo es el de Y mínima si `direccion=1`, el de Y máxima si
    `direccion=-1` -- nunca se asume Y creciente = tiempo creciente."""
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


def _validar_fisiologia(
    matriz: np.ndarray, muestras_grilla_v1: tuple[int, np.ndarray] | None, muestras_tira: np.ndarray
) -> bool:
    """Última barrera antes de aceptar la señal: cada banda de amplitud
    puede haber calibrado perfectamente y la señal seguir cruzada (columna o
    fila mal asignada). Verifica las identidades de Einthoven y Goldberger
    -- válidas en todo instante, no sólo en reposo -- sobre las derivaciones
    YA ubicadas en `matriz`, y que la V1 de la grilla (a punto de
    descartarse) coincide con el segmento equivalente de la tira. Cualquier
    residuo por fuera de umbral -- `False`, la señal se descarta completa."""
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
