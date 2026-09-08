"""Genera contenido de documento sintético A PARTIR de una plantilla real.

Tarea "invertir la dirección del corpus sintético": `pdf_sintetico.py` (antes
de este módulo) reconstruía a mano, línea por línea, una aproximación de cada
tipo de informe -- y cada estructura que quien lo escribió no conocía o se
olvidó de tipear quedaba como un hueco sin cobertura (pasó nueve veces en
este proyecto: ver la nota al pie de `matriz_cobertura_sinteticos.md`).

Este módulo invierte esa dirección: toma como MOLDE el fixture parseable
versionado de cada tipo (`tests/fixtures/parseables/{tipo}-01.txt`) --layout
real completo, ya limpio de PII (ver `src/anonimizacion/esqueleto.py`,
sección "Fixture PARSEABLE", y el centinela
`tests/deteccion/test_centinela_fixtures_parseables.py`)-- y produce, por
documento, una variante con la identidad (nombre, DNI/documento, fechas,
números de petición/estudio/ECG) sustituida por un valor sintético nuevo,
determinístico por semilla. Todo el resto del documento (secciones, notas de
método, párrafo de descargo del CKD-EPI, notas multilínea de referencia,
boilerplate institucional, firma) se conserva LITERAL: es lo que hace que la
cobertura estructural del corpus sintético valga por CONSTRUCCIÓN en vez de
por la memoria de quien mantiene el generador -- ver el centinela de
cobertura en `tests/fixtures/test_cobertura_plantillas.py`.

Reemplazo por SPANS, no por `str.replace` global: un campo corto como la edad
("70") reemplazado con `str.replace` global corrompería cualquier otro número
de dos cifras en la misma página (un resultado de laboratorio, por ejemplo).
Cada campo se ubica con el MISMO regex de `_CAMPOS_HEADER` que usa el parser
de producción correspondiente (import directo, no una copia) para no
desincronizarse si el parser cambia su calibración, y se reemplaza sólo en el
span exacto que devuelve ese regex (truncado al primer separador de 2+
espacios, misma convención que usan los tres parsers reales).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from anonimizacion.parseo.ecg_mortara import _CAMPOS_HEADER as _CAMPOS_ECG
from anonimizacion.parseo.eco_doppler import _CAMPOS_HEADER as _CAMPOS_ECO
from anonimizacion.parseo.laboratorio_general import _CAMPOS_HEADER as _CAMPOS_LAB

from .lectura_fixture_texto import leer_texto_extraido_de_fixture

_DIR_PLANTILLAS = Path(__file__).parent / "parseables"

_APELLIDOS = (
    "GOMEZ", "PEREZ", "DIAZ", "ROMERO", "SOSA", "TORRES", "MEDINA",
    "CASTRO", "NUNEZ", "VEGA", "ROJAS", "SILVA", "PAZ", "LUNA", "RIOS",
)
_NOMBRES = (
    "ANA", "LUIS", "MARIA", "JORGE", "LAURA", "PABLO", "CARLA", "DIEGO",
    "SILVIA", "RAUL", "MARCOS", "NOELIA", "HUGO", "IVANA", "OMAR",
)
_MESES_INGLES = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)


_PREFIJO_ARCHIVO = {"ecg": "ecg", "laboratorio": "laboratorio", "ecocardiograma": "eco"}


@lru_cache(maxsize=None)
def _plantilla(tipo: str):
    """Carga (y cachea) el `TextoExtraido` reconstruido del fixture parseable.

    Cacheado a propósito: el corpus de carga instancia miles de documentos
    por corrida (ver `tests/carga/ejecutar_corpus.py`) y el fixture es
    estático -- releer y reagrupar el `.txt` una vez por documento sería
    trabajo de I/O repetido sin ningún beneficio.
    """
    prefijo = _PREFIJO_ARCHIVO[tipo]
    return leer_texto_extraido_de_fixture(_DIR_PLANTILLAS / f"{prefijo}-01.txt")


def _primer_segmento(texto: str) -> str:
    """Misma convención que `_primer_segmento` de los tres parsers reales
    (idéntica en los tres, y en `esqueleto.py`): trunca en el primer salto de
    2+ espacios, separador de columnas cuando dos campos comparten fila."""
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _span_de_campo(patron: str, texto: str, *, truncar: bool = True) -> tuple[int, int] | None:
    """Ubica el span EXACTO (inicio, fin) del valor de un campo de header
    dentro de `texto`.

    `truncar=True` (default) aplica el mismo truncamiento que
    `parseo/laboratorio_general.py` y `parseo/eco_doppler.py` (`_primer_segmento`,
    corta en el primer salto de 2+ espacios) para no arrastrar el campo
    siguiente de la misma fila visual como si fuera parte de este valor.
    `parseo/ecg_mortara.py`, en cambio, NO trunca (usa `group(1).strip()` tal
    cual salvo en `institucion`/`medico_derivante`) -- su campo "fecha" tiene
    un salto de 2+ espacios INTENCIONAL entre fecha y hora que forma parte
    del valor; truncar ahí cortaría la hora. Los llamadores de este módulo
    pasan `truncar=False` para esos campos."""
    coincidencia = re.search(patron, texto)
    if coincidencia is None:
        return None
    crudo = coincidencia.group(1)
    segmento = _primer_segmento(crudo) if truncar else crudo.strip()
    if not segmento:
        return None
    offset = crudo.find(segmento)
    if offset < 0:
        return None
    inicio = coincidencia.start(1) + offset
    return inicio, inicio + len(segmento)


# Campos por tipo cuyo span NO debe truncarse en el primer salto de 2+
# espacios -- ver docstring de `_span_de_campo`.
_CAMPOS_SIN_TRUNCAR: dict[str, frozenset[str]] = {"ecg": frozenset({"fecha"})}


def _aplicar_sustituciones(
    pagina: str, campos_header: dict[str, str], sustitutos: dict[str, str], *, tipo: str = ""
) -> str:
    """Reemplaza, EN `pagina`, cada campo de `sustitutos` por su valor nuevo.

    Todos los spans se calculan sobre el texto ORIGINAL antes de tocar nada,
    y se aplican de atrás para adelante -- así el reemplazo de un campo no
    corre de lugar el offset ya calculado de otro campo previo en la misma
    página."""
    sin_truncar = _CAMPOS_SIN_TRUNCAR.get(tipo, frozenset())
    spans: list[tuple[tuple[int, int], str]] = []
    for clave, valor_nuevo in sustitutos.items():
        patron = campos_header.get(clave)
        if patron is None:
            continue
        span = _span_de_campo(patron, pagina, truncar=clave not in sin_truncar)
        if span is not None:
            spans.append((span, valor_nuevo))
    for (inicio, fin), valor_nuevo in sorted(spans, key=lambda item: item[0][0], reverse=True):
        pagina = pagina[:inicio] + valor_nuevo + pagina[fin:]
    return pagina


@dataclass(frozen=True)
class FragmentoPagina:
    """Un fragmento de texto a dibujar como un `insert_text` INDEPENDIENTE.

    `fila`/`columna` ubican el fragmento en la grilla geométrica de la
    página: `fila` es el índice de línea de `paginas_ordenadas`, `columna`
    es la posición ORDINAL (0, 1, 2...) del token dentro de esa fila -- NO
    un offset de caracter. La coordenada X real (ancho de fuente, sin
    solapar con el token anterior de la misma fila) se calcula recién al
    dibujar (`pdf_sintetico._dibujar_fragmentos_plantilla`), con
    `pymupdf.get_text_length` -- ver el hallazgo documentado ahí: un offset
    de caracter escalado a ciegas subestimaba el ancho real a fontsize
    pequeño y hacía que `get_text(sort=True)` intercalara caracteres de dos
    fragmentos vecinos ("F.Nacimiento :" + valor). El orden en que
    `_fragmentos_en_orden_de_dibujado` EMITE la lista (no la posición fila/
    columna) es lo que reproduce el orden de dibujado real -- ver esa
    función."""

    fila: int
    columna: int
    texto: str
    # `True` si, EN LA PLANTILLA, este token empieza un grupo de columna
    # nuevo (separado del anterior por 2+ espacios) -- necesita un espacio
    # ANCHO al dibujarlo para que `get_text(sort=True)` lo reconstruya
    # también separado por 2+ espacios (convención `_primer_segmento`/
    # `\\s{2,}` que usan los parsers de producción). `False` si es una
    # sub-pieza de un token que la plantilla trae unido por UN solo espacio
    # ("81 mm", "Etiqueta: valor") -- necesita un espacio ANGOSTO para que
    # `sort=True` lo reconstruya también con un solo espacio (ver hallazgo:
    # `parseo/eco_doppler.py::_parsear_fila_medidas_dos_columnas` separa
    # columnas con `\\s{2,}` -- un gap ancho entre "81" y "mm" los vuelve DOS
    # columnas en vez de un solo valor con unidad).
    separador_ancho: bool = True


_PATRON_TOKEN_COLUMNA = re.compile(r"\S.*?(?=\s{2,}|\Z)")
# Etiqueta = 1 a 4 palabras (letras/puntos) terminadas en ":" -- generaliza
# `_CAMPOS_HEADER["fecha"]` de eco (etiqueta+valor unidos por UN espacio) al
# caso de VARIAS etiquetas encadenadas en la misma fila sin separador de 2+
# espacios (p. ej. "Fecha Estudio: 12/01/2022 PACIENTE: NOMBRE" -- una sola
# fila real de la plantilla de eco).
#  Sin dígitos a propósito: excluye valores con forma de fecha/número
# ("12/01/2022") de la ventana de "palabras" de la etiqueta -- si se
# permitieran dígitos, un valor SIN etiqueta propia pegado justo antes de la
# próxima etiqueta ("Fecha Estudio: 12/01/2022 PACIENTE: ...") se tragaría
# como si fuera parte de esa etiqueta siguiente en vez de quedar aislado
# como su propio token.
_PATRON_ETIQUETAS_ENCADENADAS = re.compile(r"([^\s:\d]+(?:\s[^\s:\d]+){0,3}:)")
# Separa "81 mm" en ("81", "mm") -- celda de medida con unidad pegada por un
# solo espacio (tabla de medidas del eco). NO matchea "< 34 mm" (no arranca
# con dígito): esa forma ya es una única línea de la plantilla, no dos.
_PATRON_NUMERO_UNIDAD = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s+([A-Za-zÀ-ÿ%./]{1,10})$")


def _dividir_etiquetas_encadenadas(texto: str) -> list[str]:
    """Parte `texto` en sus etiquetas ("Palabra:") y los valores que las
    siguen, cuando hay VARIAS etiquetas pegadas en la misma fila sin
    separador de columna. Sin etiquetas reconocibles, devuelve `[texto]`
    tal cual."""
    partes = _PATRON_ETIQUETAS_ENCADENADAS.split(texto)
    if len(partes) == 1:
        return [texto]
    piezas: list[str] = []
    previo = partes[0].strip()
    if previo:
        piezas.append(previo)
    for indice in range(1, len(partes), 2):
        etiqueta = partes[indice]
        piezas.append(etiqueta)
        valor = partes[indice + 1].strip() if indice + 1 < len(partes) else ""
        if valor:
            piezas.append(valor)
    return piezas


def _dividir_numero_unidad(texto: str) -> list[str]:
    coincidencia = _PATRON_NUMERO_UNIDAD.match(texto)
    if coincidencia is None:
        return [texto]
    return [coincidencia.group(1), coincidencia.group(2)]


def _tokenizar_fila(fila: str) -> list[tuple[str, bool]]:
    """Divide UNA fila de `paginas_ordenadas` (orden geométrico) en sus
    tokens de columna, EN ORDEN IZQUIERDA A DERECHA -- misma convención de
    separador que `_primer_segmento` (2+ espacios) -- y además parte en
    piezas más finas los tokens que unen VARIAS etiquetas ("Etiqueta1:
    valor1 Etiqueta2: valor2") o un número+unidad ("81 mm") con UN solo
    espacio: el separador de 2+ espacios no alcanza para esos casos, y sin
    partirlos el `get_text()` sin `sort` del PDF generado reproduce muchas
    menos líneas que la plantilla real (Tarea 1, "usar la plantilla
    completa"). La posición ORDINAL de cada token en la lista devuelta ES su
    número de columna -- ver `FragmentoPagina`.

    Devuelve `[(texto, separador_ancho), ...]` -- `separador_ancho` marca si
    ESTE token abre un grupo de columna nuevo de la plantilla (separado del
    anterior por 2+ espacios) o es una sub-pieza de un token unido por un
    solo espacio -- ver `FragmentoPagina.separador_ancho`."""
    tokens: list[tuple[str, bool]] = []
    for coincidencia in _PATRON_TOKEN_COLUMNA.finditer(fila):
        crudo = coincidencia.group()
        inicio_de_grupo = True
        for etiqueta_o_valor in _dividir_etiquetas_encadenadas(crudo):
            for subpieza in _dividir_numero_unidad(etiqueta_o_valor):
                texto = subpieza.strip()
                if texto:
                    tokens.append((texto, inicio_de_grupo))
                    inicio_de_grupo = False
    return tokens


def _fragmentos_en_orden_de_dibujado(
    pagina_geo_original: str, pagina_geo_sustituida: str, pagina_dibujado_original: str
) -> tuple[FragmentoPagina, ...]:
    """Devuelve los fragmentos de UNA página, en el MISMO orden en que
    `pagina_dibujado_original` (sección "orden de dibujado" de la plantilla)
    los declara -- Tarea 2 de la tarea "usar la plantilla completa": producción
    extrae dos representaciones (`extraccion/texto_pymupdf.py`) que NO son
    intercambiables, y el corpus sintético debía reproducir la diferencia en
    vez de dibujar en un orden cómodo donde ambas salen casi iguales.

    Cada fragmento conserva la posición (fila/columna) que su token ocupaba
    en `pagina_geo_original` (orden geométrico) -- PyMuPDF reconstruye
    `get_text(sort=True)` por posición X/Y, NO por orden de llamada a
    `insert_text` (verificado empíricamente: ver el reporte de esta tarea),
    así que reordenar la lista de EMISIÓN no degrada la agrupación por fila
    que necesitan `parseo/laboratorio_general.py` y `parseo/eco_doppler.py`.

    Sólo se reordenan así los tokens que son ÚNICOS dentro de la página (un
    único (fila, columna) tiene ese texto exacto) -- un token repetido (p. ej.
    una unidad "%" que aparece en diez filas) no tiene una correspondencia
    inequívoca contra la lista de líneas de dibujado; forzar un match
    ambiguo arriesgaría dibujarlo en la fila equivocada, así que esos quedan
    en orden natural (fila por fila, izquierda a derecha) al final, DESPUÉS
    de los fragmentos ya ubicados con precisión. Es una limitación medida y
    reportada, no disimulada -- ver el reporte de la tarea para el número
    real de cobertura de orden que este compromiso logra."""
    tokens_originales = [_tokenizar_fila(fila) for fila in pagina_geo_original.splitlines()]
    tokens_sustituidos = [_tokenizar_fila(fila) for fila in pagina_geo_sustituida.splitlines()]
    posicion_unica = _indice_de_posiciones_unicas(tokens_originales)

    def _token_final(fila_idx: int, col_idx: int, token_original: tuple[str, bool]) -> tuple[str, bool]:
        fila_sustituida = tokens_sustituidos[fila_idx] if fila_idx < len(tokens_sustituidos) else []
        if col_idx < len(fila_sustituida):
            return fila_sustituida[col_idx]
        return token_original  # la fila cambió de forma tras sustituir -- no debería pasar contra la plantilla versionada

    usados: set[tuple[int, int]] = set()
    fragmentos: list[FragmentoPagina] = []
    for linea in pagina_dibujado_original.splitlines():
        contenido = linea.strip()
        if not contenido:
            continue
        posicion = posicion_unica.get(contenido)
        if posicion is None or posicion in usados:
            continue
        fila_idx, col_idx = posicion
        usados.add(posicion)
        texto, ancho = _token_final(fila_idx, col_idx, tokens_originales[fila_idx][col_idx])
        fragmentos.append(FragmentoPagina(fila_idx, col_idx, texto, ancho))

    for fila_idx, tokens in enumerate(tokens_sustituidos):
        for col_idx, (texto, ancho) in enumerate(tokens):
            if (fila_idx, col_idx) in usados:
                continue
            fragmentos.append(FragmentoPagina(fila_idx, col_idx, texto, ancho))

    return tuple(fragmentos)


def _indice_de_posiciones_unicas(tokens_por_fila: list[list[tuple[str, bool]]]) -> dict[str, tuple[int, int]]:
    """Mapea texto de token -> (fila, columna) para los tokens que aparecen
    UNA sola vez en toda la página -- ver docstring de
    `_fragmentos_en_orden_de_dibujado`, sección de tokens ambiguos."""
    ocurrencias: dict[str, list[tuple[int, int]]] = {}
    for fila_idx, tokens in enumerate(tokens_por_fila):
        for col_idx, (texto, _ancho) in enumerate(tokens):
            ocurrencias.setdefault(texto, []).append((fila_idx, col_idx))
    return {texto: posiciones[0] for texto, posiciones in ocurrencias.items() if len(posiciones) == 1}


def _numero_sintetico(rng: random.Random, digitos: int) -> str:
    return str(rng.randint(10 ** (digitos - 1), 10 ** digitos - 1))


def _id_interno_sintetico(rng: random.Random, prefijo: str, digitos: int) -> str:
    """Como `_numero_sintetico`, pero con un prefijo NO numérico distintivo.

    Hallazgo (banco de carga, tarea "invertir la dirección del corpus
    sintético"): un Nº de Estudio/ECG de sólo 6-7 dígitos ("405474") tiene
    probabilidad no despreciable de aparecer por COINCIDENCIA como
    subcadena de un valor hexadecimal/base64 en la salida anonimizada --
    medido contra el escalón de 1.000 documentos: `pii_en_salida` pasó de 0
    a 3 con IDs de 6 dígitos crudos. No es una fuga real (es una colisión de
    subcadena, no el mismo valor), pero degrada el propio chequeo de
    seguridad del banco (`contar_coincidencias_pii`) en un falso positivo
    que alguien terminaría por ignorar. Un prefijo alfabético (nunca
    numérico) hace que la subcadena completa sea intrínsecamente más rara en
    un string aleatorio, sin afectar el parseo real (`_CAMPOS_HEADER_ECO`/
    `_CAMPOS_HEADER_ECG` capturan el campo con `.+`/`\\S+`, no exigen
    dígitos)."""
    return f"{prefijo}-{_numero_sintetico(rng, digitos)}"


def _fecha_guion_ecg(fecha: date) -> str:
    return f"{fecha.day:02d}-{_MESES_INGLES[fecha.month - 1]}-{fecha.year}"


@dataclass(frozen=True)
class IdentidadSintetica:
    """Identidad de UN paciente sintético, compartida por sus tres documentos
    (mismo criterio que ya usaba `pdf_sintetico.py`: un solo DNI para
    laboratorio/eco, un solo nombre para los tres) -- para que el corpus siga
    describiendo un paciente coherente, no tres desconocidos sueltos."""

    apellido: str
    nombre1: str
    apellido2: str
    dni: str
    nacimiento: date

    @property
    def nombre_lab(self) -> str:
        return f"{self.apellido} , {self.nombre1} {self.apellido2}"

    @property
    def nombre_eco(self) -> str:
        return f"{self.apellido} {self.nombre1} {self.apellido2}"

    @property
    def nombre_ecg(self) -> str:
        return f"{self.apellido} {self.nombre1}"


def generar_identidad_sintetica(rng: random.Random, dni: str, fecha_referencia: date) -> IdentidadSintetica:
    apellido = rng.choice(_APELLIDOS)
    nombre1 = rng.choice(_NOMBRES)
    apellido2 = rng.choice(_APELLIDOS)
    edad = rng.randint(1, 90)
    nacimiento = fecha_referencia.replace(year=fecha_referencia.year - edad, day=min(fecha_referencia.day, 28))
    return IdentidadSintetica(apellido, nombre1, apellido2, dni, nacimiento)


def preparar_laboratorio(
    rng: random.Random, identidad: IdentidadSintetica, fecha: date
) -> tuple[tuple[tuple[FragmentoPagina, ...], ...], tuple[str, ...]]:
    """Devuelve `(paginas_a_dibujar, valores_pii_generados)` para laboratorio.

    Cada página es una tupla de `FragmentoPagina` -- ver
    `_fragmentos_en_orden_de_dibujado` -- posicionados según el orden
    GEOMÉTRICO de la plantilla (`sort=True`, el que deja "Etiqueta: valor"
    adyacentes en la misma línea reconstruida, formato que espera
    `parseo/laboratorio_general.py`) pero EMITIDOS (orden de la tupla) según
    la sección "orden de dibujado" de la plantilla -- ver
    `extraccion/texto_pymupdf.py` y el reporte de la tarea "usar la plantilla
    completa"."""
    plantilla = _plantilla("laboratorio")
    pagina1 = plantilla.paginas_ordenadas[0]
    edad = str(fecha.year - identidad.nacimiento.year)
    numero_peticion = _id_interno_sintetico(rng, "PET-SINT", 7)
    # Hora FIJA (no derivada de `rng`) a propósito: la compuerta de
    # calibración (`tests/calibracion/compuerta_laboratorio.py`) fija
    # `hora_estudio == "08:30"` como parte del contrato seguro reproducible
    # -- variarla rompería esa aserción sin aportar nada (la fecha, el DNI,
    # el nombre y el Nº de Petición ya dan de sobra entropía por documento).
    hora = "08:30"
    sustitutos = {
        "nombre": identidad.nombre_lab,
        "dni": identidad.dni,
        "fecha_nac": identidad.nacimiento.strftime("%d/%m/%Y"),
        "edad": edad,
        "numero_peticion": numero_peticion,
        "fecha": fecha.strftime("%d/%m/%Y"),
        "hora_extraccion": hora,
    }
    if _span_de_campo(_CAMPOS_LAB["numero_peticion"], pagina1) is None:
        # No debería ocurrir contra la plantilla versionada -- fallar cerrado
        # en vez de generar un documento sin Nº de Petición (el parser real
        # lo exige, `DetalleParseoIncompleto.HEADER_AUSENTE`).
        raise AssertionError("la plantilla de laboratorio no trae Nº de Petición reconocible")
    paginas_sustituidas = tuple(
        _aplicar_sustituciones(pagina, _CAMPOS_LAB, sustitutos, tipo="laboratorio")
        for pagina in plantilla.paginas_ordenadas
    )
    paginas = tuple(
        _fragmentos_en_orden_de_dibujado(pagina_original, pagina_sustituida, pagina_dibujado)
        for pagina_original, pagina_sustituida, pagina_dibujado in zip(
            plantilla.paginas_ordenadas, paginas_sustituidas, plantilla.paginas, strict=True
        )
    )
    pii = (identidad.nombre_lab, identidad.dni, sustitutos["fecha_nac"], numero_peticion)
    return paginas, pii


# Hallazgo (tarea "invertir la dirección del corpus sintético"): el pie de
# página real del eco (aviso "Informe no válido...", número de página,
# dirección/teléfono, email/sitio web) queda enmascarado por forma en la
# plantilla -- ninguna de esas 4 líneas está en `ALLOWLIST_ESTRUCTURAL`
# (`esqueleto.py` sólo protege lo que un PARSER necesita para reconciliar un
# campo, no el boilerplate del pie). Sin relabelizarlas, `es_boilerplate_eco`
# (`parseo/eco_doppler.py`) no las reconoce, quedan como "texto libre" y se
# filtran hacia la sección vecina cuando ésta continúa entre páginas (p. ej.
# "FLUJO PULMONAR", que arranca al pie de la página 1) -- la reconciliación
# rechaza esa sección con `evidencia_ausente` porque el span esperado
# (`ContenidoEco.secciones_texto`) ya no coincide con lo que
# `_seccion_anclada` puede reconstruir cruzando la página.
#
# Reportado como HALLAZGO real (no es específico del corpus sintético):
# `es_boilerplate_eco` tampoco reconoce "Informe no válido..." en el PDF
# REAL de referencia (verificado leyendo el PDF, sin copiar su contenido a
# ningún archivo) porque su prefijo en `_PREFIJOS_BOILERPLATE` no lleva tilde
# y `casefold()` no le quita los acentos a "válido" -- ver el fix aplicado en
# `parseo/eco_doppler.py`. La dirección/teléfono del instituto y el nombre
# completo de la institución (línea suelta antes de "ECOGRAFIA DOPPLER
# COLOR CARDIACA") NO tienen ningún prefijo genérico en
# `_PREFIJOS_BOILERPLATE` -- son específicos de UN instituto, así que
# agregarlos ahí filtraría (o inventaría) un dato institucional real. Acá se
# opta por relabelizar el aviso/página/email a su forma canónica NO
# identificatoria (ya reconocida por `_PREFIJOS_BOILERPLATE`) y OMITIR la
# línea de dirección/teléfono y la del nombre completo de la institución --
# igual que "Omisiones deliberadas" en `matriz_cobertura_sinteticos.md`: no
# codifican ningún dato de paciente ni cambian la detección o el parseo.
_RELABEL_BOILERPLATE_ECO: tuple[tuple[str, str], ...] = (
    # Sin tilde a propósito: `_CAMPOS_HEADER_ECO["medico_solicitante"]`
    # acepta ambas variantes (`M[eé]dico`), y sin tilde es la misma forma que
    # ya usaba el generador hand-typed anterior.
    ("Becalo Qisujijunov:", "Medico Solicitante:"),
    ("Uja.:", "Pag.:"),
    ("Q-iyax:", "E-mail:"),
    (
        "Favuzoy la urobus bev bo dalog e ri umuso ini becalo",
        "Informe no valido sin la firma y el sello del medico",
    ),
)
_LINEA_OMITIDA_ECO = "MIKAQEZIDOLAWAGU OFUG FAPAKIDUZEZIRUMOZUJAKIXAJIGOYI"


def _recuperar_boilerplate_eco(pagina: str) -> str:
    lineas = [linea for linea in pagina.splitlines() if linea.strip() != _LINEA_OMITIDA_ECO]
    pagina = "\n".join(lineas)
    for viejo, nuevo in _RELABEL_BOILERPLATE_ECO:
        pagina = pagina.replace(viejo, nuevo)
    return pagina


def preparar_ecocardiograma(
    rng: random.Random, identidad: IdentidadSintetica, fecha: date
) -> tuple[tuple[tuple[FragmentoPagina, ...], ...], tuple[str, ...]]:
    """Igual que `preparar_laboratorio`, para ecocardiograma (también orden
    geométrico: `parseo/eco_doppler.py` también lee `paginas_ordenadas`)."""
    plantilla = _plantilla("ecocardiograma")
    edad = str(fecha.year - identidad.nacimiento.year)
    numero_estudio = _id_interno_sintetico(rng, "ECO-SINT", 6)
    sustitutos = {
        "nombre": identidad.nombre_eco,
        "dni": identidad.dni,
        "edad": edad,
        "numero_estudio": numero_estudio,
        "fecha": fecha.strftime("%d/%m/%Y"),
    }
    # `_recuperar_boilerplate_eco` puede OMITIR una línea entera (`_LINEA_OMITIDA_ECO`)
    # -- eso corre los índices de fila de la página sustituida respecto de la
    # original. Se recalculan los fragmentos ANTES de recuperar/omitir nada
    # (mismo orden de filas que `plantilla.paginas_ordenadas`) y se aplica la
    # recuperación de boilerplate en cada fragmento individual, no en la
    # página ya ensamblada.
    paginas = tuple(
        _fragmentos_eco_en_orden_de_dibujado(pagina_original, sustitutos, pagina_dibujado)
        for pagina_original, pagina_dibujado in zip(plantilla.paginas_ordenadas, plantilla.paginas, strict=True)
    )
    pii = (identidad.nombre_eco, identidad.dni, numero_estudio)
    return paginas, pii


def _fragmentos_eco_en_orden_de_dibujado(
    pagina_geo_original: str, sustitutos: dict[str, str], pagina_dibujado_original: str
) -> tuple[FragmentoPagina, ...]:
    """Como `preparar_laboratorio`, pero aplicando la sustitución y la
    recuperación de boilerplate del eco (`_recuperar_boilerplate_eco`) A NIVEL
    DE FRAGMENTO -- necesario porque esa recuperación puede OMITIR una línea
    entera (`_LINEA_OMITIDA_ECO`), y `_fragmentos_en_orden_de_dibujado` asume
    que la página sustituida tiene la MISMA cantidad de filas que la
    original."""
    pagina_sustituida = _aplicar_sustituciones(pagina_geo_original, _CAMPOS_ECO, sustitutos, tipo="ecocardiograma")
    fragmentos = _fragmentos_en_orden_de_dibujado(pagina_geo_original, pagina_sustituida, pagina_dibujado_original)
    recuperados = []
    for fragmento in fragmentos:
        texto = _recuperar_boilerplate_eco(fragmento.texto)
        if texto.strip():
            recuperados.append(FragmentoPagina(fragmento.fila, fragmento.columna, texto, fragmento.separador_ancho))
    return tuple(recuperados)


_PATRON_LINEA_SEXO_ECG = re.compile(r"(\(\d+\s*yr\))\s*\S+")


def _forzar_sexo_ecg(pagina: str) -> str:
    """Reemplaza, en la línea de fecha de nacimiento/edad, el token de sexo
    por "Male" -- sustitución POSICIONAL (no por span de `_CAMPOS_HEADER_ECG`
    como el resto de los campos): el regex de "sexo" exige literalmente
    "Male"/"Female" para poder ubicar un span en el texto ORIGINAL, pero la
    plantilla real trae ese dato enmascarado por forma (no es un marcador de
    `ALLOWLIST_ESTRUCTURAL`) -- nunca hay un span que buscar. Sin esto, el
    campo queda ausente del documento generado en vez de "cubierto" (ver
    `matriz_cobertura_sinteticos.md`, fila de sexo posicional)."""
    return _PATRON_LINEA_SEXO_ECG.sub(r"\1      Male", pagina, count=1)


def preparar_ecg(
    rng: random.Random, identidad: IdentidadSintetica, fecha: date
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Igual que las anteriores, para ECG -- pero en orden de DIBUJADO: el
    orden geométrico del ECG real está documentado como inutilizable
    (`extraccion/texto_pymupdf.py`, el trazado de las derivaciones se
    superpone al header), y tanto la detección de tipo como
    `parseo/ecg_mortara.py` leen siempre el orden de dibujado."""
    id_ecg = _id_interno_sintetico(rng, "ECG-SINT", 6)
    edad = str(fecha.year - identidad.nacimiento.year)
    sustitutos = {
        "nombre": identidad.nombre_ecg,
        "id_estudio": id_ecg,
        # Hora FIJA -- misma razón que en `preparar_laboratorio`: la
        # compuerta de calibración del ECG fija `hora_estudio == "08:30:00"`.
        "fecha": f"{_fecha_guion_ecg(fecha)}  08:30:00",
        "fecha_nac": _fecha_guion_ecg(identidad.nacimiento),
        "edad": edad,
    }
    plantilla = _plantilla("ecg")
    paginas = tuple(
        _forzar_sexo_ecg(_aplicar_sustituciones(pagina, _CAMPOS_ECG, sustitutos, tipo="ecg"))
        for pagina in plantilla.paginas
    )
    pii = (identidad.nombre_ecg, id_ecg, sustitutos["fecha_nac"])
    return paginas, pii


def paginas_plantilla_geometrica(tipo: str) -> tuple[str, ...]:
    """Texto de la plantilla SIN sustituir -- usado por el centinela de
    cobertura (`test_cobertura_plantillas.py`) como referencia."""
    return _plantilla(tipo).paginas_ordenadas


def paginas_plantilla_dibujado(tipo: str) -> tuple[str, ...]:
    return _plantilla(tipo).paginas
