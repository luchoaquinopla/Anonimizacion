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
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Devuelve `(paginas_a_dibujar, valores_pii_generados)` para laboratorio.

    `paginas_a_dibujar` usa el orden GEOMÉTRICO de la plantilla (`sort=True`):
    es el que deja "Etiqueta: valor" adyacentes en la misma línea, formato que
    espera `parseo/laboratorio_general.py` -- ver `extraccion/texto_pymupdf.py`.
    """
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
    paginas = tuple(
        _aplicar_sustituciones(pagina, _CAMPOS_LAB, sustitutos, tipo="laboratorio")
        for pagina in plantilla.paginas_ordenadas
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
) -> tuple[tuple[str, ...], tuple[str, ...]]:
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
    paginas = tuple(
        _recuperar_boilerplate_eco(_aplicar_sustituciones(pagina, _CAMPOS_ECO, sustitutos, tipo="ecocardiograma"))
        for pagina in plantilla.paginas_ordenadas
    )
    pii = (identidad.nombre_eco, identidad.dni, numero_estudio)
    return paginas, pii


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
