"""Genera un esqueleto de formato -- fixture de texto sin PII a partir de un PDF real.

Tarea "herramienta de esqueleto de formato": hoy no hay ningún fixture
derivado de un documento real en `tests/` (el `.gitignore` prohíbe PDFs a
propósito: son PII real). La calibración de los parsers vive sólo en prosa
dentro de sus docstrings, así que un refactor puede descalibrarlos en
silencio sin que ningún test se entere (ya pasó dos veces: marcadores
fantasma del ECG, y los del eco corregidos en el PR #43). Este módulo es la
pieza que falta: convierte un PDF real -- que el operador tiene en su
máquina, nunca en el repositorio -- en un fixture de texto versionable.

DISEÑO: ALLOWLIST, no denylist. Deliberado -- ver `enmascarar_por_forma`.
No se usa el motor de detección de PII (`pii/motor.py`) para decidir qué
tapar: si el detector fallara, se filtraría PII real al repositorio. La
propiedad "nunca sale un nombre real" tiene que valer por CONSTRUCCIÓN, no
por la calidad de un detector. Regla aplicada:

    Todo token se enmascara por FORMA (cada corrida de letras -> una `X`
    por letra, cada corrida de dígitos -> un `0` por dígito) salvo que esté
    en una allowlist ESTRUCTURAL explícita: los marcadores de firma que ya
    usa `deteccion/firmas/` para reconocer el tipo de documento, las
    etiquetas de header que ya usan los `_CAMPOS_HEADER` de `parseo/`, y un
    puñado de unidades clínicas (mg/dL, mm, %, mEq/L, etc.) que no
    codifican identidad alguna. Espaciado, puntuación, saltos de línea y
    longitudes se preservan siempre -- es exactamente lo que define el
    layout, y lo que permite detectar que una etiqueta se movió.

`ALLOWLIST_ESTRUCTURAL` se deriva de las mismas constantes que ya usa el
código de producción (`FIRMAS`, `_CAMPOS_HEADER` de cada parser) en vez de
tipearse a mano: una lista tipeada a mano se desincroniza en silencio el
día que alguien agregue una etiqueta nueva a un parser sin acordarse de
este módulo. Donde la extracción automática no es segura (un patrón de
regex demasiado complejo para extraerle un prefijo literal confiable), se
descarta esa etiqueta en vez de adivinar -- fallar hacia MÁS enmascarado,
nunca hacia menos, es la dirección segura en esta herramienta.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.deteccion.firmas import FIRMAS
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import _CAMPOS_HEADER as _CAMPOS_HEADER_ECG
from anonimizacion.parseo.eco_doppler import _CAMPOS_HEADER as _CAMPOS_HEADER_ECO
from anonimizacion.parseo.laboratorio_general import _CAMPOS_HEADER as _CAMPOS_HEADER_LAB

# Unidades clínicas explícitas (Tarea, texto literal del pedido): no son
# derivables con seguridad de un regex de VALOR (esos regexes matchean el
# número, no la unidad que lo acompaña en el layout real) -- se declaran acá
# a mano porque son un vocabulario cerrado y estable, nunca contenido de un
# documento. Ninguna de estas cadenas puede codificar identidad de un
# paciente.
_UNIDADES_ESTRUCTURALES: tuple[str, ...] = (
    "mg/dL",
    "mg/dl",
    "meq/lt",
    "mEq/L",
    "mEq/l",
    "mm",
    "%",
    "ms",
    "seg",
    "BPM",
    "bpm",
    "g/dL",
    "m2",
    "mmHg",
)

# Caracteres especiales de regex ante los que se detiene la extracción del
# prefijo literal de un patrón -- todo lo anterior a el primero de estos es
# texto literal seguro.
_META_REGEX = set("\\().[]{}|^$*+?")
# Caracteres que, escapados con `\`, representan a sí mismos como literal
# (p. ej. `\.` en `r"F\.Nacimiento"` es el punto literal, no "cualquier
# caracter").
_ESCAPABLES = set(".^$*+?{}[]()|\\")
_PATRON_FLAGS_INLINE = re.compile(r"^(?:\(\?[a-zA-Z]+\))+")


def _prefijo_literal(patron: str) -> str | None:
    """Extrae el prefijo literal (texto seguro) de un patrón de regex.

    Best effort, fallar CERRADO: si no se puede extraer un prefijo seguro y
    suficientemente específico (menos de 2 caracteres), se descarta -- es
    preferible enmascarar de más una etiqueta rara que arriesgar un prefijo
    ambiguo en la allowlist.
    """
    resto = _PATRON_FLAGS_INLINE.sub("", patron)
    literal: list[str] = []
    indice = 0
    while indice < len(resto):
        caracter = resto[indice]
        if caracter == "\\" and indice + 1 < len(resto) and resto[indice + 1] in _ESCAPABLES:
            literal.append(resto[indice + 1])
            indice += 2
            continue
        if caracter in _META_REGEX:
            break
        literal.append(caracter)
        indice += 1
    texto = "".join(literal).strip()
    return texto if len(texto) >= 2 else None


def _etiquetas_desde_campos_header(campos_header: dict[str, str]) -> tuple[str, ...]:
    prefijos = (_prefijo_literal(patron) for patron in campos_header.values())
    return tuple(etiqueta for etiqueta in prefijos if etiqueta)


def _marcadores_de_firmas() -> tuple[str, ...]:
    return tuple(marcador for firma in FIRMAS for marcador in firma.marcadores)


def _construir_allowlist() -> tuple[str, ...]:
    etiquetas = (
        _marcadores_de_firmas()
        + _etiquetas_desde_campos_header(_CAMPOS_HEADER_ECG)
        + _etiquetas_desde_campos_header(_CAMPOS_HEADER_ECO)
        + _etiquetas_desde_campos_header(_CAMPOS_HEADER_LAB)
        + _UNIDADES_ESTRUCTURALES
    )
    # Únicas, más largas primero: si dos etiquetas se solapan en el texto
    # (p. ej. una es prefijo de la otra), el `re` alternado igual prioriza
    # la primera alternativa que matchea en esa posición -- ordenar por
    # longitud descendente hace que la más específica gane.
    return tuple(sorted(set(etiquetas), key=len, reverse=True))


#: Vocabulario estructural completo, derivado de las constantes que el
#: propio código de producción ya declara (ver docstring del módulo).
ALLOWLIST_ESTRUCTURAL: tuple[str, ...] = _construir_allowlist()


def _patron_termino(etiqueta: str) -> str:
    """Límite de palabra en los extremos que son alfanuméricos.

    Sin esto, una etiqueta corta y genérica como "Hora" (laboratorio)
    dejaría un fragmento de un nombre real como "Horacio" sin enmascarar --
    ver `test_etiqueta_no_enmascara_substring_dentro_de_un_nombre_real`. No
    se agrega límite del lado que termina en un caracter no alfanumérico
    (p. ej. "ID:" seguido de un valor pegado, sin espacio) porque `\\b`
    ahí exigiría que el caracter siguiente NO sea alfanumérico, y en el
    layout real el valor viene pegado sin espacio (`ID:900321`).
    """
    escapada = re.escape(etiqueta)
    prefijo = r"\b" if etiqueta[:1].isalnum() else ""
    sufijo = r"\b" if etiqueta[-1:].isalnum() else ""
    return f"{prefijo}{escapada}{sufijo}"


def _compilar_patron_allowlist(etiquetas: tuple[str, ...]) -> re.Pattern[str]:
    if not etiquetas:
        return re.compile(r"(?!)")  # patrón que nunca matchea nada
    return re.compile("|".join(_patron_termino(etiqueta) for etiqueta in etiquetas), re.IGNORECASE)


_PATRON_ALLOWLIST = _compilar_patron_allowlist(ALLOWLIST_ESTRUCTURAL)
# Corridas de letras Unicode (`[^\W\d_]` = "caracter de palabra que no es
# dígito ni guión bajo" = letra) o de dígitos -- cada corrida se reemplaza
# como una unidad para preservar su longitud exacta.
_PATRON_FORMA = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def _reemplazar_por_forma(coincidencia: re.Match[str]) -> str:
    token = coincidencia.group()
    relleno = "0" if token[0].isdigit() else "X"
    return relleno * len(token)


def enmascarar_por_forma(texto: str) -> str:
    """Enmascara TODO el texto por forma, salvo los términos de la allowlist.

    Preserva espaciado, puntuación, saltos de línea y longitudes -- lo que
    define el layout. Ver el docstring del módulo para la justificación
    completa de por qué esto es una allowlist y no un denylist.
    """
    piezas: list[str] = []
    posicion = 0
    for coincidencia in _PATRON_ALLOWLIST.finditer(texto):
        piezas.append(_PATRON_FORMA.sub(_reemplazar_por_forma, texto[posicion : coincidencia.start()]))
        piezas.append(coincidencia.group())  # preservado tal cual, sin tocar
        posicion = coincidencia.end()
    piezas.append(_PATRON_FORMA.sub(_reemplazar_por_forma, texto[posicion:]))
    return "".join(piezas)


def _puntaje_de_tipo(tipo: TipoDocumento, texto_normalizado: str) -> tuple[int, int]:
    """`(marcadores que matchearon, total de marcadores de esa firma)` --
    `(0, 0)` si `tipo` es `TIPO_NO_RECONOCIDO` (ninguna firma le corresponde)."""
    for firma in FIRMAS:
        if firma.tipo is tipo:
            return firma.puntaje(texto_normalizado), len(firma.marcadores)
    return 0, 0


@dataclass(frozen=True)
class Esqueleto:
    """Resultado de `generar_esqueleto`: texto enmascarado + evidencia de detección."""

    tipo_detectado: TipoDocumento
    puntaje: int
    total_marcadores: int
    paginas: tuple[str, ...]
    paginas_ordenadas: tuple[str, ...]

    def formatear(self) -> str:
        """Fixture de texto legible y versionable con ambas representaciones."""
        lineas = [
            "# esqueleto de formato -- generado con `anonimizacion esqueleto`",
            f"# tipo_detectado: {self.tipo_detectado.value}",
            f"# puntaje_firma: {self.puntaje}/{self.total_marcadores} marcadores",
            "",
        ]
        for numero, pagina in enumerate(self.paginas, start=1):
            lineas.append(f"## pagina {numero} (orden de dibujado)")
            lineas.append(pagina)
        for numero, pagina in enumerate(self.paginas_ordenadas, start=1):
            lineas.append(f"## pagina {numero} (orden geometrico)")
            lineas.append(pagina)
        return "\n".join(lineas)


def generar_esqueleto(texto: TextoExtraido) -> Esqueleto:
    """Genera el esqueleto: detecta el tipo y enmascara AMBAS representaciones.

    Reproduce las dos representaciones de `TextoExtraido` (`paginas` y
    `paginas_ordenadas`) porque el ECG se calibra contra la primera y
    laboratorio/eco contra la segunda (ver `extraccion/texto_pymupdf.py`) --
    un esqueleto que sólo reprodujera una de las dos no serviría para
    calibrar el otro camino.
    """
    texto_normalizado = texto.texto_completo.upper()
    tipo_detectado = detectar_tipo(texto)
    puntaje, total_marcadores = _puntaje_de_tipo(tipo_detectado, texto_normalizado)
    return Esqueleto(
        tipo_detectado=tipo_detectado,
        puntaje=puntaje,
        total_marcadores=total_marcadores,
        paginas=tuple(enmascarar_por_forma(pagina) for pagina in texto.paginas),
        paginas_ordenadas=tuple(enmascarar_por_forma(pagina) for pagina in texto.paginas_ordenadas),
    )


# ---------------------------------------------------------------------------
# Fixture PARSEABLE -- Tarea "fixture parseable de esqueletos reales".
#
# `generar_esqueleto` (arriba) sólo prueba DETECCIÓN DE TIPO y ESTABILIDAD DE
# LAYOUT: los valores están tapados por forma, así que ningún test contra ese
# fixture puede afirmar que un parser extrae bien los datos. `generar_fixture_parseable`
# reusa EXACTAMENTE la misma allowlist estructural (`ALLOWLIST_ESTRUCTURAL`,
# `_PATRON_ALLOWLIST`) -- no se toca el criterio de qué es estructura y qué es
# contenido -- y cambia sólo la función de sustitución: en vez de `X`/`0` por
# forma, un sustituto plausible de la MISMA forma (misma cantidad de dígitos,
# misma longitud de palabra, misma mayús/minús carácter a carácter).
#
# Requisito duro de determinismo: cada sustitución es una función PURA del
# token original (hash SHA-256 con un salt fijo), nunca de su posición ni de
# un generador aleatorio con estado -- el mismo valor de entrada produce
# siempre el mismo sustituto, aparezca donde aparezca en el documento. Esto
# no es un detalle de estilo: `parseo/laboratorio_general.py` (`parsear`)
# exige que el Nº de Petición no cambie entre páginas del mismo documento; si
# la sustitución dependiera de la posición, ese chequeo del parser real
# fallaría contra el propio fixture que se supone que debe validarlo.
#
# Fechas y horas son un caso aparte: sustituir sus dígitos de forma genérica
# produciría "45/78/1234" o "99:99". Se detectan por forma (`DD/MM/AAAA`,
# `DD-MMM-AAAA`, `HH:MM[:SS]`) y se sustituyen por una fecha/hora VÁLIDA. Para
# los campos de header que sí importan clínicamente (fecha de nacimiento,
# fecha de estudio, edad) se resuelve además la coherencia: la fecha de
# nacimiento sintética se construye a partir de la fecha de estudio sintética
# menos una edad sintética (mismo mes/día, año restado) -- `nacimiento <
# estudio` vale por construcción, sin necesidad de resolver años bisiestos ni
# límites de mes, porque `_fecha_sintetica` ya acota el día a 1-28. Cualquier
# otra fecha/hora del documento (no ligada a un campo de header conocido)
# recibe igual una fecha/hora VÁLIDA, sólo que sin relación de orden
# garantizada con las demás -- no hay con qué ser coherente.
# ---------------------------------------------------------------------------

_MESES_INGLES_ABREVIADOS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)

# Alfabetos para el generador de "palabras" sustitutas -- alternar
# consonante/vocal produce algo pronunciable (p. ej. "Bafo", "Ruko") en vez de
# ruido tipo "Xkqz", sin pretender ser un diccionario de nombres reales.
_CONSONANTES = "bcdfghjklmnpqrstvwxyz"
_VOCALES = "aeiou"

# Alternativas ordenadas por especificidad: una fecha+hora completa de ECG
# tiene que ganarle a "sólo la fecha" en la misma posición, o el fragmento de
# hora quedaría suelto y lo capturaría el grupo `hora` por separado (perdiendo
# la correspondencia exacta con la clave del mapa de coherencia).
_PATRON_TOKEN_VALOR = re.compile(
    r"(?P<fecha_hora_ecg>\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})"
    r"|(?P<fecha_guion>\d{2}-[A-Za-z]{3}-\d{4})"
    r"|(?P<fecha_barra>\d{2}/\d{2}/\d{4})"
    r"|(?P<hora>\d{2}:\d{2}(?::\d{2})?)"
    r"|(?P<letras>[^\W\d_]+)"
    r"|(?P<digitos>\d+)",
    re.UNICODE,
)
_PATRON_FECHA_Y_HORA_ECG = re.compile(r"^(\d{2}-[A-Za-z]{3}-\d{4})(\s+)(\d{2}:\d{2}:\d{2})$")

# Protección ADICIONAL a `ALLOWLIST_ESTRUCTURAL`, sólo para el fixture
# PARSEABLE: constantes de vocabulario cerrado (nombres de sección, palabras
# de una medida, el sufijo "yr" de la edad) que cada parser real necesita
# encontrar LITERAL para reconciliar el documento, pero que la allowlist
# derivada de `FIRMAS`/`_CAMPOS_HEADER` deja afuera porque nunca las
# necesitó: el esqueleto ENMASCARADO no vuelve a parsearse, así que nunca le
# importó si "MEDIDAS" o "PR interval" sobrevivían literales. Ninguna de
# estas cadenas puede codificar identidad de un paciente -- mismo principio
# que `_UNIDADES_ESTRUCTURALES`, arriba.
#
# Dos formas de protección, según si la constante tiene un "valor" variable
# pegado al lado (que sí debe sustituirse) o no:
#
# 1) Etiqueta + valor (`_spans_de_etiquetas`): protege sólo hasta el inicio
#    del grupo capturado, dejando el valor en la sustitución normal.
#    - LABORATORIO: "Nº Petición:"/"Médico:" quedan ENTERAMENTE fuera de la
#      allowlist -- su prefijo literal seguro (`_prefijo_literal`, arriba)
#      mide menos de 2 caracteres antes de la clase de regex que matchea la
#      variante acentuada del símbolo de grado/ordinal (`N[ºo°]`/`M[eé]dico`).
#      Para "Nº Petición:" esto no es cosmético: sin ella reconocible en
#      ninguna página, `ParseadorLaboratorioGeneral.parsear` nunca completa
#      el header y aborta (`HEADER_AUSENTE`) en vez de parsear. "Hora de
#      Extracción:" está sólo a medias: la allowlist cubre "Hora" (prefijo
#      literal seguro antes del grupo opcional `(?:\s+de)?`) pero no
#      "de Extracción:".
#    - ECOCARDIOGRAMA: "Nº Estudio:" tiene el mismo problema de clase de
#      regex que "Nº Petición:". "Matrícula" (firma del médico informante,
#      `_PATRON_MATRICULA` de `eco_doppler.py`) no tiene ningún prefijo
#      literal derivable (no es un campo de `_CAMPOS_HEADER`) -- sin ella
#      reconocible, `firma` queda siempre en `None`.
#    Deliberadamente NO se usa el header completo de ECG: el patrón `sexo`
#    de `_CAMPOS_HEADER_ECG` capturaría como "etiqueta" toda la fecha de
#    nacimiento + edad que lo precede en la misma línea -- la MISMA región
#    que ya resuelve `_construir_mapa_fechas_horas` con coherencia clínica --
#    y protegerla literalmente filtraría la fecha de nacimiento y la edad
#    REALES al fixture.
#
# 2) Palabra suelta sin valor (`_compilar_patron_allowlist`, reusada tal
#    cual): protege el match completo, nada que sustituir al lado.
#    - ECOCARDIOGRAMA: nombres de sección/subsección (`_SECCIONES_TEXTO`,
#      `_SECCION_MEDIDAS`, `_SUBSECCIONES` de `eco_doppler.py`) -- sin ellos
#      literales, el parser nunca abre ninguna sección y `medidas`/
#      `secciones_texto` quedan vacíos aunque el parseo no aborte.
#    - ECG: "yr" (sufijo de edad, `_CAMPOS_HEADER_ECG["fecha_nac"/"edad"]`) y
#      las etiquetas de medida que NO son marcador de firma ("PR interval",
#      "QRS duration", "QT/QTc" -- a diferencia de "VENT. RATE"/"P-R-T AXES",
#      que sí lo son y ya sobreviven vía `ALLOWLIST_ESTRUCTURAL`).
_ETIQUETAS_SECCION_ECO: tuple[str, ...] = (
    "MEDIDAS",
    "MOTILIDAD SEGMENTARIA",
    "VALVULAS CARDIACAS",
    "AURICULAS",
    "PERICARDIO",
    "EVALUACION DE FLUJOS POR DOPPLER",
    "CONCLUSIONES",
    "AORTICA",
    "MITRAL",
    "PULMONAR",
    "TRICUSPIDEA",
    "IZQUIERDA",
    "DERECHA",
    "FLUJO AORTICO",
    "FLUJO MITRAL",
    "FLUJO PULMONAR",
    "FLUJO TRICUSPIDEO",
    # Valores cualitativos de un vocabulario cerrado que la tabla real de
    # medidas usa en vez de un número (`_es_nombre_de_medida` de
    # `eco_doppler.py` los excluye explícitamente de "nombre de medida" para
    # reconocerlos como VALOR) -- si se sustituyeran por una palabra
    # genérica, el parser los tomaría por el nombre de la SIGUIENTE medida en
    # vez de por el valor de la actual. Igual que las unidades: vocabulario
    # cerrado, nunca identidad de un paciente.
    "NORMAL",
    "VARIABLE",
)
_PATRON_ETIQUETAS_SECCION_ECO = _compilar_patron_allowlist(_ETIQUETAS_SECCION_ECO)
_PATRON_MATRICULA_ECO = re.compile(r"Matr[ií]cula\s+([A-Za-z])\s*(\d+)", re.IGNORECASE)

_ETIQUETAS_MEDIDA_ECG: tuple[str, ...] = ("yr", "PR interval", "QRS duration", "QT/QTc")
_PATRON_ETIQUETAS_MEDIDA_ECG = _compilar_patron_allowlist(_ETIQUETAS_MEDIDA_ECG)


def _spans_protegidos_adicionales(pagina: str, tipo_detectado: TipoDocumento) -> list[tuple[int, int]]:
    if tipo_detectado is TipoDocumento.LABORATORIO:
        return _spans_de_etiquetas(
            pagina,
            {
                "numero_peticion": _CAMPOS_HEADER_LAB["numero_peticion"],
                "medico_derivante": _CAMPOS_HEADER_LAB["medico_derivante"],
                "hora_extraccion": _CAMPOS_HEADER_LAB["hora_extraccion"],
            },
        )
    if tipo_detectado is TipoDocumento.ECOCARDIOGRAMA:
        spans = _spans_de_etiquetas(
            pagina,
            {
                "numero_estudio": _CAMPOS_HEADER_ECO["numero_estudio"],
                "matricula": "(?i)" + _PATRON_MATRICULA_ECO.pattern,
            },
        )
        spans.extend((m.start(), m.end()) for m in _PATRON_ETIQUETAS_SECCION_ECO.finditer(pagina))
        return spans
    if tipo_detectado is TipoDocumento.ECG:
        return [(m.start(), m.end()) for m in _PATRON_ETIQUETAS_MEDIDA_ECG.finditer(pagina)]
    return []


def _entero_deterministico(semilla: str, minimo: int, maximo: int) -> int:
    """Entero reproducible en `[minimo, maximo]`, función PURA de `semilla`.

    Determinismo por HASH del string de entrada -- no de posición en el
    documento ni de un generador con estado -- ver docstring de la sección
    de arriba sobre por qué esto es un requisito duro, no un detalle.
    """
    digest = hashlib.sha256(semilla.encode("utf-8")).digest()
    valor = int.from_bytes(digest[:8], "big")
    return minimo + valor % (maximo - minimo + 1)


def _sustituir_digitos(token: str) -> str:
    """Otro número de la MISMA cantidad de dígitos, reproducible por token.

    Cada corrida de dígitos se sustituye de forma independiente (ver
    `_PATRON_TOKEN_VALOR`: cada `\\d+` es un match separado), así que un
    valor con decimales -- dos corridas separadas por un punto, p. ej. "3.5"
    son los matches "3" y "5" -- preserva automáticamente la cantidad de
    decimales: cada corrida mantiene su propia longitud.
    """
    digest = hashlib.sha256(f"digitos|{token}".encode()).digest()
    digitos = [str(digest[indice % len(digest)] % 10) for indice in range(len(token))]
    if token[0] != "0" and digitos[0] == "0":
        digitos[0] = str((digest[0] % 9) + 1)
    return "".join(digitos)


def _sustituir_letras(token: str) -> str:
    """Otra "palabra" de la MISMA longitud, alternando consonante/vocal.

    Preserva mayús/minús carácter a carácter -- "Gutierrez" (mayús + minúsc.)
    sigue siendo mayús + minúsc., "MARCELA" (todo mayúsculas) sigue siendo
    todo mayúsculas -- necesario porque algún marcador podría depender de la
    caja (mismo motivo que documenta `enmascarar_por_forma`).
    """
    digest = hashlib.sha256(f"letras|{token.lower()}".encode()).digest()
    fase_vocal = digest[0] % 2
    letras: list[str] = []
    for indice, original in enumerate(token):
        es_vocal = (indice + fase_vocal) % 2 == 1
        alfabeto = _VOCALES if es_vocal else _CONSONANTES
        letra = alfabeto[digest[(indice + 1) % len(digest)] % len(alfabeto)]
        letras.append(letra.upper() if original.isupper() else letra)
    return "".join(letras)


def _fecha_sintetica(semilla: str) -> date:
    """Fecha VÁLIDA reproducible. Día acotado a 1-28 a propósito: evita
    lidiar con límites de mes (Abr/Sep/Jun/Nov = 30 días) y con años
    bisiestos al restarle la edad después (`_mapa_fechas_horas_lab` y
    afines) -- un 29 de febrero sintético podría caer en un año no bisiesto
    al restarle la edad y producir una fecha inválida."""
    dia = 1 + _entero_deterministico(f"dia|{semilla}", 0, 27)
    mes = 1 + _entero_deterministico(f"mes|{semilla}", 0, 11)
    anio = _entero_deterministico(f"anio|{semilla}", 2015, 2025)
    return date(anio, mes, dia)


def _hora_sintetica(semilla: str) -> tuple[int, int, int]:
    hora = _entero_deterministico(f"hora|{semilla}", 0, 23)
    minuto = _entero_deterministico(f"minuto|{semilla}", 0, 59)
    segundo = _entero_deterministico(f"segundo|{semilla}", 0, 59)
    return hora, minuto, segundo


def _edad_sintetica(semilla: str) -> int:
    return _entero_deterministico(f"edad|{semilla}", 1, 90)


def _formatear_fecha_barra(fecha: date) -> str:
    return fecha.strftime("%d/%m/%Y")


def _formatear_fecha_guion(fecha: date) -> str:
    return f"{fecha.day:02d}-{_MESES_INGLES_ABREVIADOS[fecha.month - 1]}-{fecha.year}"


def _formatear_hora(hora: int, minuto: int, segundo: int | None) -> str:
    if segundo is None:
        return f"{hora:02d}:{minuto:02d}"
    return f"{hora:02d}:{minuto:02d}:{segundo:02d}"


def _tiene_segundos(texto_hora: str) -> bool:
    return texto_hora.count(":") == 2


def _sustituto_fecha_hora_independiente(original: str, grupo: str | None) -> str:
    """Sustituto VÁLIDO para un token con forma de fecha/hora que no es uno
    de los campos de header con coherencia clínica resuelta (ver
    `_construir_mapa_fechas_horas`) -- sigue siendo una fecha/hora válida,
    sólo que sin relación de orden garantizada con otras fechas del
    documento: no hay con qué ser coherente."""
    if grupo == "fecha_hora_ecg":
        coincidencia = _PATRON_FECHA_Y_HORA_ECG.match(original)
        assert coincidencia is not None  # garantizado por el grupo que matcheó
        espacio = coincidencia.group(2)
        fecha_str = _formatear_fecha_guion(_fecha_sintetica(original))
        hora_h, hora_m, hora_s = _hora_sintetica(original)
        return f"{fecha_str}{espacio}{_formatear_hora(hora_h, hora_m, hora_s)}"
    if grupo == "fecha_guion":
        return _formatear_fecha_guion(_fecha_sintetica(original))
    if grupo == "fecha_barra":
        return _formatear_fecha_barra(_fecha_sintetica(original))
    hora_h, hora_m, hora_s = _hora_sintetica(original)
    return _formatear_hora(hora_h, hora_m, hora_s if _tiene_segundos(original) else None)


def _reemplazar_token_valor(coincidencia: re.Match[str], mapa_fechas_horas: dict[str, str]) -> str:
    """El mapa de coherencia se consulta PRIMERO sin importar qué grupo
    matcheó -- no sólo para los grupos con forma de fecha/hora. La edad
    (`_mapa_fechas_horas_lab`/`_mapa_fechas_horas_ecg`) se guarda bajo su
    string de dígitos original tal cual (p. ej. "64"), que matchea el grupo
    genérico `digitos`, no uno de los grupos de fecha/hora -- si el chequeo
    del mapa se limitara a esos grupos, la edad sintética nunca se aplicaría
    y quedaría un número sin relación con las fechas sustituidas."""
    original = coincidencia.group()
    grupo = coincidencia.lastgroup
    sustituto_coherente = mapa_fechas_horas.get(original)
    if sustituto_coherente is not None:
        return sustituto_coherente
    if grupo in ("fecha_hora_ecg", "fecha_guion", "fecha_barra", "hora"):
        return _sustituto_fecha_hora_independiente(original, grupo)
    if grupo == "letras":
        return _sustituir_letras(original)
    return _sustituir_digitos(original)  # grupo == "digitos"


def _sustituir_valores_en_segmento(segmento: str, mapa_fechas_horas: dict[str, str]) -> str:
    return _PATRON_TOKEN_VALOR.sub(lambda m: _reemplazar_token_valor(m, mapa_fechas_horas), segmento)


def _primer_segmento_valor(texto: str) -> str:
    """Mismo criterio que `_primer_segmento` de los tres parsers de `parseo/`
    (idéntico en los tres): trunca en el primer salto de 2+ espacios,
    separador de columnas del reporte real cuando dos campos comparten la
    misma fila visual. Reimplementado acá en vez de importar las tres
    versiones privadas -- son idénticas entre sí, una sola copia local es más
    simple que tres imports con alias para la misma línea de código."""
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _campos_fecha_lab(texto: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave in ("fecha_nac", "fecha", "edad", "hora_extraccion"):
        coincidencia = re.search(_CAMPOS_HEADER_LAB[clave], texto)
        if coincidencia is not None:
            campos[clave] = _primer_segmento_valor(coincidencia.group(1))
    return campos


def _campos_fecha_eco(texto: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave in ("fecha", "edad"):
        coincidencia = re.search(_CAMPOS_HEADER_ECO[clave], texto)
        if coincidencia is not None:
            campos[clave] = _primer_segmento_valor(coincidencia.group(1))
    return campos


def _campos_fecha_ecg(texto: str) -> dict[str, str]:
    """A diferencia de laboratorio/eco, `parseo/ecg_mortara.py::_buscar_campos`
    NO aplica `_primer_segmento` a los campos de fecha (sólo a `institucion`/
    `medico_derivante`, después de la extracción) -- truncar acá cortaría la
    hora si el separador de 2+ espacios cae ENTRE la fecha y la hora, que es
    exactamente el layout real (`DD-MON-YYYY␣␣HH:MM:SS`)."""
    campos: dict[str, str] = {}
    for clave in ("fecha", "fecha_nac", "edad"):
        coincidencia = re.search(_CAMPOS_HEADER_ECG[clave], texto)
        if coincidencia is not None:
            campos[clave] = coincidencia.group(1).strip()
    return campos


def _mapa_fechas_horas_lab(texto: str) -> dict[str, str]:
    campos = _campos_fecha_lab(texto)
    mapa: dict[str, str] = {}
    fecha_estudio: date | None = None
    if "fecha" in campos:
        fecha_estudio = _fecha_sintetica(campos["fecha"])
        mapa[campos["fecha"]] = _formatear_fecha_barra(fecha_estudio)
    if fecha_estudio is not None and "fecha_nac" in campos:
        edad = _edad_sintetica(campos.get("edad", campos["fecha_nac"]))
        nacimiento = fecha_estudio.replace(year=fecha_estudio.year - edad)
        mapa[campos["fecha_nac"]] = _formatear_fecha_barra(nacimiento)
        if "edad" in campos:
            mapa[campos["edad"]] = str(edad)
    if "hora_extraccion" in campos:
        hora_h, hora_m, hora_s = _hora_sintetica(campos["hora_extraccion"])
        mapa[campos["hora_extraccion"]] = _formatear_hora(
            hora_h, hora_m, hora_s if _tiene_segundos(campos["hora_extraccion"]) else None
        )
    return mapa


def _mapa_fechas_horas_eco(texto: str) -> dict[str, str]:
    """El eco no trae fecha de nacimiento en el header (ver
    `parseo/eco_doppler.py`) -- no hay con qué reconciliar la edad, así que
    queda a cargo de la sustitución genérica de dígitos (sigue siendo un
    número válido, sólo que sin relación cruzada con ninguna fecha)."""
    campos = _campos_fecha_eco(texto)
    if "fecha" not in campos:
        return {}
    return {campos["fecha"]: _formatear_fecha_barra(_fecha_sintetica(campos["fecha"]))}


def _mapa_fechas_horas_ecg(texto: str) -> dict[str, str]:
    campos = _campos_fecha_ecg(texto)
    mapa: dict[str, str] = {}
    fecha_estudio: date | None = None
    if "fecha" in campos:
        coincidencia = _PATRON_FECHA_Y_HORA_ECG.match(campos["fecha"])
        if coincidencia is not None:
            fecha_estudio = _fecha_sintetica(campos["fecha"])
            hora_h, hora_m, hora_s = _hora_sintetica(campos["fecha"])
            mapa[campos["fecha"]] = (
                f"{_formatear_fecha_guion(fecha_estudio)}{coincidencia.group(2)}"
                f"{_formatear_hora(hora_h, hora_m, hora_s)}"
            )
    if fecha_estudio is not None and "fecha_nac" in campos:
        edad = _edad_sintetica(campos.get("edad", campos["fecha_nac"]))
        nacimiento = fecha_estudio.replace(year=fecha_estudio.year - edad)
        mapa[campos["fecha_nac"]] = _formatear_fecha_guion(nacimiento)
        if "edad" in campos:
            mapa[campos["edad"]] = str(edad)
    return mapa


def _construir_mapa_fechas_horas(tipo_detectado: TipoDocumento, texto: TextoExtraido) -> dict[str, str]:
    """Mapa `fecha/hora original -> sustituto sintético coherente`, construido
    UNA sola vez por documento a partir de los campos de header que cada
    parser real ya sabe leer (`_CAMPOS_HEADER_LAB/ECO/ECG`). Cada tipo lee la
    representación de `texto` que su parser de producción realmente consume
    (ver docstring de `TextoExtraido` y de `generar_esqueleto`)."""
    if tipo_detectado is TipoDocumento.LABORATORIO:
        return _mapa_fechas_horas_lab(texto.texto_completo_ordenado)
    if tipo_detectado is TipoDocumento.ECOCARDIOGRAMA:
        return _mapa_fechas_horas_eco(texto.texto_completo_ordenado)
    if tipo_detectado is TipoDocumento.ECG:
        return _mapa_fechas_horas_ecg(texto.texto_completo)
    return {}


def _spans_de_etiquetas(pagina: str, etiquetas: dict[str, str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for patron in etiquetas.values():
        coincidencia = re.search(patron, pagina)
        if coincidencia is not None and coincidencia.start() < coincidencia.start(1):
            spans.append((coincidencia.start(), coincidencia.start(1)))
    return spans


def _fusionar_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Colapsa spans solapados/adyacentes en su unión.

    Necesario porque una etiqueta de `etiquetas_adicionales` (p. ej. "Hora de
    Extracción:") puede EMPEZAR en el mismo punto que un span más chico ya
    cubierto por `ALLOWLIST_ESTRUCTURAL` (la propia palabra "Hora") -- sin
    fusionar, el span más grande quedaría descartado por "solapa con uno ya
    emitido" en vez de extender la protección hasta donde corresponde,
    dejando "de Extracción:" sin proteger.
    """
    if not spans:
        return []
    ordenados = sorted(spans)
    fusionados = [ordenados[0]]
    for inicio, fin in ordenados[1:]:
        ultimo_inicio, ultimo_fin = fusionados[-1]
        if inicio <= ultimo_fin:
            fusionados[-1] = (ultimo_inicio, max(ultimo_fin, fin))
        else:
            fusionados.append((inicio, fin))
    return fusionados


def sustituir_por_valores_plausibles(
    texto: str, mapa_fechas_horas: dict[str, str], tipo_detectado: TipoDocumento
) -> str:
    """Igual que `enmascarar_por_forma` (misma allowlist, mismo criterio de
    qué preservar) pero sustituye lo que NO está en la allowlist por
    contenido SINTÉTICO plausible en vez de taparlo por forma -- ver
    docstring de la sección de arriba.

    Además de `ALLOWLIST_ESTRUCTURAL`, protege las etiquetas/constantes que
    el parser real de `tipo_detectado` necesita encontrar literalmente para
    reconciliar el documento pero que la allowlist deja afuera o cubre sólo
    a medias (ver `_spans_protegidos_adicionales`) -- sin esto el fixture
    parseable no sería, de hecho, parseable.
    """
    spans = [(coincidencia.start(), coincidencia.end()) for coincidencia in _PATRON_ALLOWLIST.finditer(texto)]
    spans.extend(_spans_protegidos_adicionales(texto, tipo_detectado))
    spans = _fusionar_spans(spans)

    piezas: list[str] = []
    posicion = 0
    for inicio, fin in spans:
        piezas.append(_sustituir_valores_en_segmento(texto[posicion:inicio], mapa_fechas_horas))
        piezas.append(texto[inicio:fin])
        posicion = fin
    piezas.append(_sustituir_valores_en_segmento(texto[posicion:], mapa_fechas_horas))
    return "".join(piezas)


@dataclass(frozen=True)
class FixtureParseable:
    """Resultado de `generar_fixture_parseable`: mismo layout real que
    `Esqueleto`, pero con valores SINTÉTICOS plausibles en vez de tapado por
    forma -- ver el docstring de la sección de arriba."""

    tipo_detectado: TipoDocumento
    paginas: tuple[str, ...]
    paginas_ordenadas: tuple[str, ...]

    def formatear(self) -> str:
        """Mismo formato serializado que `Esqueleto.formatear()` (encabezados
        `## pagina N (orden de ...)`) a propósito: permite reusar el mismo
        lector de fixtures en los tests (ver
        `tests/fixtures/lectura_fixture_texto.py`)."""
        lineas = [
            "# fixture parseable -- generado con `anonimizacion esqueleto --modo parseable`",
            f"# tipo_detectado: {self.tipo_detectado.value}",
            "# ADVERTENCIA: todos los valores son SINTETICOS -- ninguno es un dato real de paciente.",
            "",
        ]
        for numero, pagina in enumerate(self.paginas, start=1):
            lineas.append(f"## pagina {numero} (orden de dibujado)")
            lineas.append(pagina)
        for numero, pagina in enumerate(self.paginas_ordenadas, start=1):
            lineas.append(f"## pagina {numero} (orden geometrico)")
            lineas.append(pagina)
        return "\n".join(lineas)


def generar_fixture_parseable(texto: TextoExtraido) -> FixtureParseable:
    """Genera un fixture PARSEABLE: mismo layout real que `generar_esqueleto`,
    pero con valores sintéticos plausibles en vez de tapado por forma -- ver
    el docstring de la sección de arriba para el diseño completo.
    """
    tipo_detectado = detectar_tipo(texto)
    mapa_fechas_horas = _construir_mapa_fechas_horas(tipo_detectado, texto)
    return FixtureParseable(
        tipo_detectado=tipo_detectado,
        paginas=tuple(
            sustituir_por_valores_plausibles(pagina, mapa_fechas_horas, tipo_detectado) for pagina in texto.paginas
        ),
        paginas_ordenadas=tuple(
            sustituir_por_valores_plausibles(pagina, mapa_fechas_horas, tipo_detectado)
            for pagina in texto.paginas_ordenadas
        ),
    )
