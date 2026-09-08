"""Centinela de regresión: la detección de tipo sigue funcionando sobre los
esqueletos versionados de documentos reales del Instituto de Cardiología de
Corrientes (`tests/fixtures/esqueletos/`, generados con
`anonimizacion esqueleto` a partir de PDFs reales que nunca se versionan --
ver `esqueleto.py`).

Motivo de este test: hasta ahora esos esqueletos existían en el repo pero
ningún test los leía. Archivos sueltos en un directorio no protegen nada --
si un refactor descalibra un parser o una firma en silencio, nada lo nota
(ya pasó dos veces con marcadores fantasma: ECG y ecocardiograma, ver
docstrings de `firmas/ecg_mortara.py` y `firmas/eco_doppler.py`).

LIMITACIÓN DELIBERADA -- léase con atención: el esqueleto tiene los VALORES
enmascarados por forma (diseño allowlist, ver docstring de `esqueleto.py`).
Este centinela cubre DETECCIÓN DE TIPO Y LAYOUT ESTRUCTURAL (qué encabezados
y marcadores de firma sobreviven, con qué puntaje), NO PARSEO. No afirma
que los parsers extraigan bien los valores de un documento real -- eso
exigiría un fixture con datos reales, que por diseño de `esqueleto.py`
nunca existe versionado en este repositorio.

DISEÑO CRÍTICO -- por qué los pisos están hardcodeados acá: las expectativas
(tipo esperado, puntaje mínimo) NO se leen del comentario de cabecera del
propio esqueleto (`# tipo_detectado:` / `# puntaje_firma:`). Si este test
leyera esos comentarios, alguien que regenere un esqueleto con un detector
ya roto grabaría el resultado roto en la cabecera y el test seguiría en
verde -- lavando exactamente la regresión que existe para atrapar. Los
pisos de abajo son los puntajes medidos HOY contra el documento real
(`anonimizacion esqueleto <pdf>`); si alguien retira de una firma un
marcador que sí aparece en el documento real, el puntaje medido cae por
debajo del piso hardcodeado y el test falla.

Representación consumida -- corrección de una premisa: `detectar_tipo`
(`deteccion/detector_tipo.py`) siempre lee `texto.texto_completo`, que es
`paginas` (orden de DIBUJADO), para los TRES tipos de documento por igual --
nunca lee `paginas_ordenadas` (orden geométrico), ni siquiera para
laboratorio o ecocardiograma. La distinción dibujado/geométrico que sí
existe en producción es de PARSEO, no de detección: `parseo/ecg_mortara.py`
lee `texto.paginas` (dibujado) y `parseo/laboratorio_general.py` /
`parseo/eco_doppler.py` leen `texto.paginas_ordenadas` (geométrico) para
extraer CAMPOS, pero la detección de TIPO -- la única responsabilidad que
este centinela cubre -- es un único call site (`pipeline/ejecutor.py`) que
siempre pasa por `texto.texto_completo` = `paginas`, sea cual sea el tipo.
Por eso los tres esqueletos de abajo se evalúan sobre `paginas` (orden de
dibujado): es la única representación que `detectar_tipo` consume en
producción.

Nota aparte (no corregida acá, fuera de alcance de este test): el docstring
de `extraccion/texto_pymupdf.py::TextoExtraido` afirma que la detección de
tipo "es indistinta a cuál [representación] se use". Medido contra
`ecg-01.txt`, eso es falso: el puntaje de la firma ECG cae de 3/4 (orden de
dibujado, lo que producción realmente usa) a 1/4 (orden geométrico) si se
evaluara sobre la otra representación. Un futuro refactor que confiara en
ese comentario y cambiara `detectar_tipo` a leer `paginas_ordenadas`
degradaría la evidencia de ECG en silencio.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.deteccion.firmas import FIRMAS
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from tests.fixtures.lectura_fixture_texto import leer_texto_extraido_de_fixture

_DIRECTORIO_ESQUELETOS = Path(__file__).parent.parent / "fixtures" / "esqueletos"


def _leer_esqueleto(nombre_archivo: str) -> TextoExtraido:
    """Delegación fina al lector compartido (ver
    `tests/fixtures/lectura_fixture_texto.py`) -- se conserva esta función
    local para no tocar el resto de este archivo, que ya la invoca con sólo
    el nombre de archivo (relativo a `_DIRECTORIO_ESQUELETOS`)."""
    return leer_texto_extraido_de_fixture(_DIRECTORIO_ESQUELETOS / nombre_archivo)


def _puntaje_de_firma(tipo: TipoDocumento, texto_normalizado: str) -> int:
    (firma,) = [f for f in FIRMAS if f.tipo is tipo]
    return firma.puntaje(texto_normalizado)


# Pisos medidos HOY contra los PDFs reales del Instituto de Cardiología de
# Corrientes vía `anonimizacion esqueleto <pdf>` (orden de dibujado, la
# representación que `detectar_tipo` realmente consume -- ver docstring del
# módulo). Hardcodeados a propósito: NUNCA leer del comentario de cabecera
# del propio esqueleto.
_CASOS = (
    pytest.param("ecg-01.txt", TipoDocumento.ECG, 3, id="ecg"),
    pytest.param("eco-01.txt", TipoDocumento.ECOCARDIOGRAMA, 5, id="eco"),
    pytest.param("laboratorio-01.txt", TipoDocumento.LABORATORIO, 4, id="laboratorio"),
)


@pytest.mark.parametrize("nombre_archivo, tipo_esperado, piso_puntaje", _CASOS)
def test_esqueleto_real_se_sigue_detectando_con_piso_de_evidencia(
    nombre_archivo: str, tipo_esperado: TipoDocumento, piso_puntaje: int
) -> None:
    texto = _leer_esqueleto(nombre_archivo)

    tipo_detectado = detectar_tipo(texto)
    assert tipo_detectado is tipo_esperado, (
        f"'{nombre_archivo}' se detectaba como {tipo_esperado.value}, "
        f"ahora se detecta como {tipo_detectado.value}"
    )

    puntaje = _puntaje_de_firma(tipo_esperado, texto.texto_completo.upper())
    assert puntaje >= piso_puntaje, (
        f"'{nombre_archivo}' bajo de {piso_puntaje} a {puntaje} marcadores de firma -- "
        "algun marcador que aparece en el documento real se retiro de la firma"
    )
