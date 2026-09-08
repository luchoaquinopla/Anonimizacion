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

import re
from dataclasses import dataclass

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
