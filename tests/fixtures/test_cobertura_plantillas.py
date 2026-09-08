"""Centinela de cobertura estructural del corpus sintético contra las
plantillas reales versionadas (tarea "invertir la dirección del corpus
sintético", ver el docstring de `plantilla_documento.py`).

Mide qué porcentaje del VOCABULARIO ESTRUCTURAL de cada plantilla real
(`tests/fixtures/parseables/{tipo}-01.txt`) reproduce el PDF que
`generar_corpus_clinico` termina escribiendo -- extraído con `pymupdf`, el
mismo camino que usa producción (`extraccion/texto_pymupdf.py`), no leyendo
el `.txt` de la plantilla directamente. Es justamente lo que faltaba: antes
de esta tarea, ningún test comparaba el corpus sintético contra el layout
real completo, así que un generador hand-typed podía "olvidarse" de una
estructura entera (el párrafo de descargo del CKD-EPI, notas multilínea de
referencia, boilerplate institucional) sin que nada lo notara -- pasó nueve
veces en este proyecto (ver `matriz_cobertura_sinteticos.md`).

DISEÑO -- por qué el piso está escrito acá y no calculado del propio corpus:
si el piso se derivara de la corrida actual (p. ej. "cobertura de hoy menos
1%"), un generador que se rompiera de a poco nunca hondearía la alarma: cada
regresión se convertiría en el nuevo piso aceptado. El `0.95` de
`_PISO_COBERTURA` es un literal fijo, medido una vez contra la implementación
actual (ver el reporte de la tarea) y nunca leído de un cálculo derivado.

DISEÑO -- por qué el denominador excluye identidad y boilerplate
recuperado: la meta NO es que el documento sintético sea un calco byte a
byte de la plantilla -- el requisito duro de la propia tarea es que la
identidad (nombre, DNI, fechas, números de petición/estudio/ECG) DEBE variar
por documento, si no el corpus deja de ejercitar la deduplicación por
SHA-256. Contar esas palabras como "cobertura perdida" penalizaría
exactamente la variación que la tarea pide. Ídem con el boilerplate del eco
que `plantilla_documento._recuperar_boilerplate_eco` relabeliza o quita a
propósito (ver su propio docstring: "informe no válido...", número de
página, la línea de dirección/teléfono del instituto y el nombre completo de
la institución -- ninguno de los cuatro tiene un ancla que un parser
necesite tal cual, y dos de ellos no tienen NINGÚN prefijo genérico seguro en
`_PREFIJOS_BOILERPLATE` sin inventar o filtrar un dato institucional real).

Las exclusiones se calculan invocando la MISMA función/regex de producción
que hace la sustitución (`_span_de_campo` sobre `_CAMPOS_HEADER_*`, más las
constantes ya declaradas de `_recuperar_boilerplate_eco`) -- nunca una lista
de palabras tipeada a mano por fuera de esas fuentes. Esto es deliberado: si
mañana alguien agrega un campo nuevo a `sustitutos` sin agregarlo también a
`_CLAVES_IDENTIDAD` de este archivo, ese campo NO se excluye del
denominador, así que una sustitución nueva que además pierda contenido real
sigue haciendo caer la cobertura medida -- el centinela no puede auto-
neutralizarse agregando de más a la lista de excepciones sin que alguien lo
edite a mano y lo revise.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pymupdf
import pytest

from anonimizacion.parseo.ecg_mortara import _CAMPOS_HEADER as _CAMPOS_ECG
from anonimizacion.parseo.eco_doppler import _CAMPOS_HEADER as _CAMPOS_ECO
from anonimizacion.parseo.laboratorio_general import _CAMPOS_HEADER as _CAMPOS_LAB
from tests.fixtures.pdf_sintetico import generar_corpus_clinico
from tests.fixtures.plantilla_documento import (
    _LINEA_OMITIDA_ECO,
    _PATRON_LINEA_SEXO_ECG,
    _RELABEL_BOILERPLATE_ECO,
    _span_de_campo,
    paginas_plantilla_dibujado,
    paginas_plantilla_geometrica,
)

# Piso FIJO -- ver docstring del módulo. Medido una vez contra la corrida
# actual (ecg ~100%, laboratorio ~100%, ecocardiograma ~100% tras excluir
# identidad/boilerplate recuperado); se deja margen bajo 100% a propósito
# para no ser frágil ante variaciones legítimas de redondeo/tokenización.
_PISO_COBERTURA = 0.95

_PATRON_PALABRA = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

_CAMPOS_POR_TIPO = {"ecg": _CAMPOS_ECG, "laboratorio": _CAMPOS_LAB, "ecocardiograma": _CAMPOS_ECO}
# Mismas claves que cada `preparar_*` de `plantilla_documento.py` declara en
# su diccionario `sustitutos` -- si un campo nuevo se agrega ahí sin
# agregarse acá, deja de excluirse (ver docstring del módulo).
_CLAVES_IDENTIDAD = {
    "ecg": ("nombre", "id_estudio", "fecha", "fecha_nac", "edad"),
    "laboratorio": ("nombre", "dni", "fecha_nac", "edad", "numero_peticion", "fecha", "hora_extraccion"),
    "ecocardiograma": ("nombre", "dni", "edad", "numero_estudio", "fecha"),
}
_CAMPOS_SIN_TRUNCAR_POR_TIPO = {"ecg": frozenset({"fecha"})}


def _vocabulario(texto: str) -> frozenset[str]:
    return frozenset(palabra.upper() for palabra in _PATRON_PALABRA.findall(texto))


def _texto_plantilla_original(tipo: str) -> str:
    """Misma representación que consume `plantilla_documento.py` para
    dibujar cada tipo: dibujado para ECG (el orden geométrico real está
    documentado como inutilizable, ver `extraccion/texto_pymupdf.py`),
    geométrico para laboratorio/eco."""
    paginas = paginas_plantilla_dibujado(tipo) if tipo == "ecg" else paginas_plantilla_geometrica(tipo)
    return "\n".join(paginas)


def _vocabulario_identidad(tipo: str, texto_original: str) -> frozenset[str]:
    campos = _CAMPOS_POR_TIPO[tipo]
    sin_truncar = _CAMPOS_SIN_TRUNCAR_POR_TIPO.get(tipo, frozenset())
    vocab: set[str] = set()
    for clave in _CLAVES_IDENTIDAD[tipo]:
        span = _span_de_campo(campos[clave], texto_original, truncar=clave not in sin_truncar)
        if span is not None:
            inicio, fin = span
            vocab |= _vocabulario(texto_original[inicio:fin])
    return frozenset(vocab)


def _vocabulario_boilerplate_recuperado_eco() -> frozenset[str]:
    vocab = set(_vocabulario(_LINEA_OMITIDA_ECO))
    for viejo, _nuevo in _RELABEL_BOILERPLATE_ECO:
        vocab |= _vocabulario(viejo)
    return frozenset(vocab)


def _vocabulario_sexo_ecg(texto_original: str) -> frozenset[str]:
    coincidencia = _PATRON_LINEA_SEXO_ECG.search(texto_original)
    return _vocabulario(coincidencia.group()) if coincidencia is not None else frozenset()


def _vocabulario_excluido(tipo: str, texto_original: str) -> frozenset[str]:
    excluido = set(_vocabulario_identidad(tipo, texto_original))
    if tipo == "ecocardiograma":
        excluido |= _vocabulario_boilerplate_recuperado_eco()
    if tipo == "ecg":
        excluido |= _vocabulario_sexo_ecg(texto_original)
    return frozenset(excluido)


def _texto_generado(tipo: str, semilla: int) -> str:
    with tempfile.TemporaryDirectory() as directorio:
        corpus = generar_corpus_clinico(Path(directorio), semilla=semilla)
        ruta = next(documento.ruta for documento in corpus.documentos if documento.tipo == tipo)
        pdf = pymupdf.open(ruta)
        piezas = [pagina.get_text("text", sort=True) for pagina in pdf]
        piezas.extend(pagina.get_text("text") for pagina in pdf)
        pdf.close()
    return "\n".join(piezas)


def medir_cobertura(tipo: str, semilla: int) -> tuple[float, frozenset[str], int]:
    """Devuelve `(cobertura, faltantes, tamano_del_vocabulario_exigido)`."""
    texto_original = _texto_plantilla_original(tipo)
    vocab_original = _vocabulario(texto_original)
    vocab_excluido = _vocabulario_excluido(tipo, texto_original)
    vocab_exigido = vocab_original - vocab_excluido
    vocab_generado = _vocabulario(_texto_generado(tipo, semilla))
    faltantes = vocab_exigido - vocab_generado
    if not vocab_exigido:
        return 1.0, frozenset(), 0
    cobertura = len(vocab_exigido & vocab_generado) / len(vocab_exigido)
    return cobertura, faltantes, len(vocab_exigido)


@pytest.mark.parametrize("tipo", ("ecg", "laboratorio", "ecocardiograma"))
def test_documento_sintetico_reproduce_el_piso_de_vocabulario_estructural_real(tipo: str) -> None:
    cobertura, faltantes, tamano = medir_cobertura(tipo, semilla=54321)

    assert cobertura >= _PISO_COBERTURA, (
        f"cobertura estructural de '{tipo}' cayó a {cobertura:.2%} "
        f"(piso {_PISO_COBERTURA:.0%}, sobre {tamano} palabras exigidas) -- "
        f"faltan: {sorted(faltantes)}"
    )


def test_el_piso_de_cobertura_detecta_una_regresion_real(monkeypatch) -> None:
    """Prueba el propio centinela: si `generar_corpus_clinico` dejara de
    dibujar el cuerpo tomado de la plantilla (la regresión concreta que esta
    tarea existe para impedir que vuelva a pasar desapercibida), este test
    debe fallar. Se verifica monkeyparacheando `_dibujar_cuerpo_plantilla`
    a un no-op -- no se toca el generador real."""
    import tests.fixtures.pdf_sintetico as pdf_sintetico

    monkeypatch.setattr(pdf_sintetico, "_dibujar_cuerpo_plantilla", lambda *args, **kwargs: None)

    cobertura, _faltantes, _tamano = medir_cobertura("laboratorio", semilla=54321)

    assert cobertura < _PISO_COBERTURA, (
        "el centinela de cobertura no detectó que el cuerpo de la plantilla "
        "dejó de dibujarse -- dejaría pasar la misma regresión que esta "
        "tarea existe para impedir"
    )
