"""Mide la fidelidad de ORDEN del corpus sintético contra las dos
representaciones que expone `extraccion/texto_pymupdf.py` -- Tarea 2 de la
tarea "usar la plantilla completa".

Por qué esto es un test aparte de `test_fidelidad_lineas_plantillas.py`
(cantidad de líneas) y `test_cobertura_plantillas.py` (vocabulario): ninguno
de los dos mide SECUENCIA. Antes de esta tarea, laboratorio/eco dibujaban
UNA cadena ya fusionada por fila, así que el orden de dibujado
(`get_text()`) y el orden geométrico (`get_text(sort=True)`) del PDF
generado salían casi idénticos entre sí -- ningún test ejercitaba la razón
por la que `TextoExtraido` expone las dos representaciones por separado (ver
`extraccion/texto_pymupdf.py`).

MÉTRICA -- "fidelidad de orden" = proporción de líneas de la plantilla real
que aparecen en el PDF generado en el MISMO ORDEN RELATIVO (subsecuencia
común más larga -- LIS sobre las posiciones de cada línea de plantilla
dentro del texto generado, consumiendo duplicados en orden de aparición).
No exige que sean ADYACENTES, sólo que no estén invertidas entre sí.

HONESTIDAD DEL NÚMERO -- la plantilla real todavía trae la identidad VIEJA
(nombre/DNI/fechas sintéticos del fixture, no los que genera esta corrida),
así que las líneas de identidad NUNCA matchean literal contra el PDF
generado (que sustituye esos valores) -- la métrica los cuenta como "no
encontrados", lo que originalmente PISOnaría el número hacia abajo. Se
decidió NO excluirlos (a diferencia de `test_cobertura_plantillas.py`,
que sí excluye identidad de su denominador): esto es TEXTO en secuencia,
no vocabulario, y armar una lista de exclusión por posición sería
exactamente el tipo de "mover el denominador" que esta tarea existe para
evitar. El número de abajo es el real, con esa penalización incluida.

Los pisos son literales fijos, medidos UNA VEZ contra esta implementación
(semilla 777) -- ver el reporte de la tarea "usar la plantilla completa"
para los números completos por tipo. Se prioriza el orden de DIBUJADO (el
que reproduce con más fidelidad, ver `plantilla_documento.py`); el
geométrico se mide y se reporta, con piso bajo a propósito -- NO se fuerza
a un número alto artificialmente.

CIERRE DEL GAP DE DIBUJADO (tarea "cerrar la fidelidad de orden") --
`_fragmentos_en_orden_de_dibujado` (`plantilla_documento.py`) anclaba sólo
los tokens ÚNICOS en toda la página; un token repetido (p. ej. la unidad "%"
en diez filas de la tabla de laboratorio) no tenía correspondencia
inequívoca y quedaba relegado a orden natural al final, castigando la
fidelidad medida. Se resolvió por CONTEXTO (`_asignar_posiciones_por_contexto`):
los tokens únicos siguen de ancla, y cada ocurrencia ambigua se ubica dentro
de la ventana de filas delimitada por las anclas más cercanas antes/después
en la secuencia de dibujado -- alineamiento de secuencias sobre el contexto
vecino, no búsqueda de tokens sueltos. Subió laboratorio (71.7% -> 90.7%) y
ecocardiograma (60.1% -> 78.6%); ecg no cambia (90.4%) porque
`preparar_ecg` no pasa por esa función (dibuja la plantilla literal, ver
`plantilla_documento.py`). El geométrico no se mueve por este cambio (mismo
número que antes): reordena la EMISIÓN, no la posición física (fila,
columna) de cada fragmento, y `get_text(sort=True)` reconstruye por
posición, no por orden de inserción.
"""

from __future__ import annotations

import bisect
import tempfile
from collections import deque
from pathlib import Path

import pymupdf
import pytest

from tests.fixtures.pdf_sintetico import generar_corpus_clinico
from tests.fixtures.plantilla_documento import paginas_plantilla_dibujado, paginas_plantilla_geometrica

# Piso FIJO de fidelidad de orden de DIBUJADO -- se prioriza este (Tarea 2,
# "insertar los fragmentos en el mismo orden en que la plantilla los
# declara"). Medido tras cerrar el gap con emparejamiento por contexto (ver
# docstring del módulo): ecg 90.4% (sin cambios), laboratorio 90.7% (era
# 71.7%), ecocardiograma 78.6% (era 60.1%) -- semilla 777. Piso con margen
# bajo esos números, no igual a ellos.
_PISO_FIDELIDAD_DIBUJADO = {"ecg": 0.80, "laboratorio": 0.80, "ecocardiograma": 0.65}

# Piso FIJO de fidelidad de orden GEOMÉTRICO -- reportado, NO forzado a un
# número alto. Medido: ecg 3.7% (esperado: el geométrico del ECG real está
# documentado como inutilizable, `extraccion/texto_pymupdf.py`), laboratorio
# 30.5%, ecocardiograma 61.5%. El piso sólo protege contra una regresión
# hacia CERO (p. ej. que la reconstrucción de columnas se rompa del todo),
# no exige que el número suba.
_PISO_FIDELIDAD_GEOMETRICO = {"ecg": 0.0, "laboratorio": 0.15, "ecocardiograma": 0.30}


def _lis_longitud(posiciones: list[int]) -> int:
    colas: list[int] = []
    for posicion in posiciones:
        indice = bisect.bisect_left(colas, posicion)
        if indice == len(colas):
            colas.append(posicion)
        else:
            colas[indice] = posicion
    return len(colas)


def _fidelidad_de_orden(lineas_plantilla: list[str], lineas_generadas: list[str]) -> float:
    """Proporción de `lineas_plantilla` que aparece, en el mismo orden
    relativo, dentro de `lineas_generadas` -- ver docstring del módulo."""
    if not lineas_plantilla:
        return 1.0
    disponibles: dict[str, deque[int]] = {}
    for indice, linea in enumerate(lineas_generadas):
        disponibles.setdefault(linea, deque()).append(indice)
    posiciones = []
    for linea in lineas_plantilla:
        cola = disponibles.get(linea)
        if cola:
            posiciones.append(cola.popleft())
    return _lis_longitud(posiciones) / len(lineas_plantilla)


def _lineas_no_vacias(paginas: tuple[str, ...]) -> list[str]:
    return [linea.strip() for pagina in paginas for linea in pagina.splitlines() if linea.strip()]


def _generar_y_extraer(tipo: str, semilla: int) -> tuple[list[str], list[str]]:
    """Devuelve `(lineas_dibujado, lineas_geometricas)` extraídas del PDF que
    `generar_corpus_clinico` termina escribiendo para `tipo`."""
    with tempfile.TemporaryDirectory() as directorio:
        corpus = generar_corpus_clinico(Path(directorio), semilla=semilla)
        ruta = next(documento.ruta for documento in corpus.documentos if documento.tipo == tipo)
        pdf = pymupdf.open(ruta)
        dibujado: list[str] = []
        geometrico: list[str] = []
        for pagina in pdf:
            dibujado.extend(linea.strip() for linea in pagina.get_text().splitlines() if linea.strip())
            geometrico.extend(linea.strip() for linea in pagina.get_text(sort=True).splitlines() if linea.strip())
        pdf.close()
    return dibujado, geometrico


@pytest.mark.parametrize("tipo", ("ecg", "laboratorio", "ecocardiograma"))
def test_fidelidad_de_orden_de_dibujado_no_regresiona(tipo: str) -> None:
    gen_dibujado, _gen_geo = _generar_y_extraer(tipo, semilla=777)
    tmpl_dibujado = _lineas_no_vacias(paginas_plantilla_dibujado(tipo))

    fidelidad = _fidelidad_de_orden(tmpl_dibujado, gen_dibujado)

    assert fidelidad >= _PISO_FIDELIDAD_DIBUJADO[tipo], (
        f"fidelidad de orden de DIBUJADO de '{tipo}' cayó a {fidelidad:.1%} "
        f"(piso {_PISO_FIDELIDAD_DIBUJADO[tipo]:.0%})"
    )


@pytest.mark.parametrize("tipo", ("ecg", "laboratorio", "ecocardiograma"))
def test_fidelidad_de_orden_geometrico_se_reporta_sin_forzarse(tipo: str) -> None:
    """El piso acá es deliberadamente bajo -- ver docstring del módulo. Este
    test existe para que una regresión hacia CERO (la reconstrucción de
    columnas rompiéndose del todo) se note, no para exigir un número alto:
    reproducir EXACTAMENTE las dos representaciones a la vez puede no ser
    posible (columnas fusionadas de forma distinta entre dibujado y
    geométrico, ver `plantilla_documento.py`)."""
    _gen_dibujado, gen_geo = _generar_y_extraer(tipo, semilla=777)
    tmpl_geo = _lineas_no_vacias(paginas_plantilla_geometrica(tipo))

    fidelidad = _fidelidad_de_orden(tmpl_geo, gen_geo)

    assert fidelidad >= _PISO_FIDELIDAD_GEOMETRICO[tipo], (
        f"fidelidad de orden GEOMÉTRICO de '{tipo}' cayó a {fidelidad:.1%} "
        f"(piso {_PISO_FIDELIDAD_GEOMETRICO[tipo]:.0%})"
    )
