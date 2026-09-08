"""Centinela de LÍNEAS del corpus sintético contra la plantilla real
(tarea "usar la plantilla completa").

Distinto del centinela de VOCABULARIO (`test_cobertura_plantillas.py`):
medir vocabulario (el conjunto de palabras que aparece en algún lado) no
detecta que el generador dibuje MENOS LÍNEAS que la plantilla real -- si el
mismo conjunto de palabras se reparte en menos renglones (columnas
fusionadas en una sola cadena), el vocabulario sigue dando ~100% aunque las
DOS representaciones que expone `extraccion/texto_pymupdf.py` (orden de
dibujado / orden geométrico) terminen siendo casi idénticas entre sí, que es
justamente lo que este centinela existe para impedir que vuelva a pasar
desapercibido (medido antes de esta tarea: laboratorio 91/226 líneas, eco
68/173, con el mismo vocabulario "100%" del otro centinela).

DISEÑO -- por qué el piso es un literal fijo y no un cálculo del propio
corpus: mismo argumento que `test_cobertura_plantillas.py` -- si el piso se
derivara de la corrida actual, una regresión gradual nunca la detectaría
(cada caída se convertiría en el nuevo piso aceptado). Los números de abajo
salen de medir la plantilla real UNA VEZ (ver
`plantilla_documento.paginas_plantilla_dibujado`, que reconstruye
`## pagina N (orden de dibujado)` de cada fixture parseable) y el reporte de
la tarea "usar la plantilla completa".
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf
import pytest

from tests.fixtures.pdf_sintetico import generar_corpus_clinico
from tests.fixtures.plantilla_documento import paginas_plantilla_dibujado

# Líneas no vacías de la plantilla real, en orden de dibujado (medidas contra
# `tests/fixtures/parseables/{tipo}-01.txt` -- ver docstring del módulo).
# ecg=52 (1 página), laboratorio=226 (3 páginas: 99+94+33), ecocardiograma=173
# (2 páginas: 123+50).
_LINEAS_PLANTILLA = {"ecg": 52, "laboratorio": 226, "ecocardiograma": 173}
_PAGINAS_PLANTILLA = {"ecg": 1, "laboratorio": 3, "ecocardiograma": 2}

# Piso FIJO por tipo -- literal, NO calculado como "95% de lo de arriba" en
# tiempo de ejecución (ver DISEÑO en el docstring del módulo). Son los
# enteros de `_LINEAS_PLANTILLA * 0.95`, redondeados hacia abajo, congelados
# acá como número concreto.
_PISO_LINEAS = {"ecg": 49, "laboratorio": 214, "ecocardiograma": 164}


def _lineas_no_vacias_generadas(tipo: str, semilla: int) -> tuple[int, int]:
    """Devuelve `(cantidad_de_lineas_no_vacias, cantidad_de_paginas)` del PDF
    que `generar_corpus_clinico` termina escribiendo para `tipo`, leído sin
    `sort` (orden de dibujado, el mismo camino que
    `extraccion/texto_pymupdf.py::TextoExtraido.paginas`)."""
    with tempfile.TemporaryDirectory() as directorio:
        corpus = generar_corpus_clinico(Path(directorio), semilla=semilla)
        ruta = next(documento.ruta for documento in corpus.documentos if documento.tipo == tipo)
        pdf = pymupdf.open(ruta)
        texto = "".join(pagina.get_text() for pagina in pdf)
        paginas = pdf.page_count
        pdf.close()
    return sum(1 for linea in texto.splitlines() if linea.strip()), paginas


@pytest.mark.parametrize("tipo", ("ecg", "laboratorio", "ecocardiograma"))
def test_documento_sintetico_reproduce_el_piso_de_lineas_de_la_plantilla(tipo: str) -> None:
    lineas, paginas = _lineas_no_vacias_generadas(tipo, semilla=12345)

    assert paginas == _PAGINAS_PLANTILLA[tipo], (
        f"'{tipo}' generó {paginas} página(s), la plantilla real trae {_PAGINAS_PLANTILLA[tipo]}"
    )
    assert lineas >= _PISO_LINEAS[tipo], (
        f"'{tipo}' generó {lineas} líneas no vacías (orden de dibujado) -- "
        f"piso {_PISO_LINEAS[tipo]} (95% de las {_LINEAS_PLANTILLA[tipo]} líneas de la plantilla real)"
    )


def test_la_plantilla_real_no_cambio_de_tamano_sin_que_se_note() -> None:
    """Si alguien reemplaza un fixture `parseables/{tipo}-01.txt` por una
    plantilla de otro tamaño, `_LINEAS_PLANTILLA`/`_PISO_LINEAS` (literales
    de este módulo) quedarían desincronizados en silencio -- este test lo
    nota explícitamente en vez de dejar que el piso simplemente se vuelva
    más fácil o más difícil de cumplir sin que nadie lo revise."""
    for tipo, esperado in _LINEAS_PLANTILLA.items():
        paginas = paginas_plantilla_dibujado(tipo)
        medido = sum(len([linea for linea in pagina.splitlines() if linea.strip()]) for pagina in paginas)
        assert medido == esperado, (
            f"la plantilla real de '{tipo}' ahora tiene {medido} líneas (orden de dibujado), "
            f"no {esperado} -- actualizar `_LINEAS_PLANTILLA`/`_PISO_LINEAS` a mano tras revisar por qué cambió"
        )


def test_el_piso_de_lineas_detecta_una_regresion_real(monkeypatch) -> None:
    """Prueba el propio centinela: si el cuerpo dejara de dibujarse (la
    regresión concreta que esta tarea existe para impedir), este test debe
    fallar. Se verifica monkeypracheando las dos funciones de dibujado de
    cuerpo (`_dibujar_cuerpo_plantilla` para ECG, `_dibujar_fragmentos_plantilla`
    para laboratorio/eco) a no-ops -- no se toca el generador real."""
    import tests.fixtures.pdf_sintetico as pdf_sintetico

    monkeypatch.setattr(pdf_sintetico, "_dibujar_cuerpo_plantilla", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdf_sintetico, "_dibujar_fragmentos_plantilla", lambda *args, **kwargs: None)

    for tipo in ("ecg", "laboratorio", "ecocardiograma"):
        lineas, _paginas = _lineas_no_vacias_generadas(tipo, semilla=12345)
        assert lineas < _PISO_LINEAS[tipo], (
            f"el centinela de líneas no detectó que el cuerpo de '{tipo}' dejó de dibujarse -- "
            "dejaría pasar la misma regresión que esta tarea existe para impedir"
        )
