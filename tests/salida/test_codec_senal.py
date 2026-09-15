"""Tests de `salida/codec_senal.py` (tasks.md 2.1, openspec `senal-ecg-y-dataset-vinculado`).

Lección de la entrega 1: un fixture que comparte la fórmula del código bajo
prueba no es un oráculo, es un espejo. Por eso, además del ida y vuelta,
estos tests fijan bytes/valores conocidos calculados a mano o con
`zlib`/`numpy` crudo (nunca reusando `codificar_muestras`/`codificar_mascara`
para verificarse a sí mismos).
"""

from __future__ import annotations

import zlib

import numpy as np
import pytest

from anonimizacion.dominio.senal_ecg import FORMA
from anonimizacion.salida.codec_senal import (
    VERSION_FORMATO_ACTUAL,
    codificar_mascara,
    codificar_muestras,
    decodificar_mascara,
    decodificar_muestras,
)


def _matriz_con(valor: int) -> np.ndarray:
    matriz = np.zeros(FORMA, dtype=np.int16)
    matriz[0, 0] = valor
    return matriz


def test_codificar_muestras_produce_bytes_int16_little_endian_conocidos() -> None:
    """1,234 mV -> 1234 uV (ver `extraccion/senal_ecg.py::_muestrear`, que ya
    hace `mv * 1000` antes de llegar acá): valor conocido a mano, no derivado
    de la misma fórmula que codifica. Oráculo independiente: se descomprime
    con `zlib` crudo y se lee el byte 0/1 de la matriz linealizada en C-order
    sin pasar por `decodificar_muestras`."""
    matriz = _matriz_con(1234)

    crudo = zlib.decompress(codificar_muestras(matriz))

    assert crudo[:2] == (1234).to_bytes(2, byteorder="little", signed=True)
    assert len(crudo) == FORMA[0] * FORMA[1] * 2


def test_codificar_muestras_no_recorta_ni_altera_los_extremos_de_int16() -> None:
    """Los valores ya vienen saturados/validados por `extraccion/senal_ecg.py`
    (rechazo todo-o-nada de la geometría, nunca clamping numérico) antes de
    llegar al codec -- este módulo NUNCA recorta ni reinterpreta: sólo
    empaqueta bytes. Se fija con los dos extremos representables de int16."""
    matriz = np.zeros(FORMA, dtype=np.int16)
    matriz[0, 0] = -32768
    matriz[0, 1] = 32767

    decodificada = decodificar_muestras(codificar_muestras(matriz))

    assert decodificada[0, 0] == -32768
    assert decodificada[0, 1] == 32767


def test_codificar_muestras_ida_y_vuelta_preserva_matriz_aleatoria() -> None:
    rng = np.random.default_rng(42)
    matriz = rng.integers(-32768, 32767, size=FORMA, dtype=np.int16)

    assert np.array_equal(decodificar_muestras(codificar_muestras(matriz)), matriz)


def test_codificar_mascara_produce_bits_empaquetados_conocidos() -> None:
    """Oráculo independiente: se arma la máscara esperada con `np.packbits`
    aplicado a mano sobre un patrón fijo, no reusando `codificar_mascara`."""
    mascara = np.zeros(FORMA, dtype=bool)
    mascara[0, :8] = [True, False, True, False, False, False, False, True]

    crudo = zlib.decompress(codificar_mascara(mascara))
    primer_byte = np.frombuffer(crudo, dtype=np.uint8)[0]

    assert primer_byte == 0b10100001


def test_codificar_mascara_ida_y_vuelta_preserva_mascara() -> None:
    mascara = np.zeros(FORMA, dtype=bool)
    mascara[3, 100:200] = True
    mascara[11, :] = True

    assert np.array_equal(decodificar_mascara(codificar_mascara(mascara)), mascara)


@pytest.mark.parametrize("forma_invalida", [(11, 5000), (12, 4999)])
def test_decodificar_muestras_rechaza_bytes_de_forma_incorrecta(forma_invalida: tuple[int, int]) -> None:
    matriz_ajena = np.zeros(forma_invalida, dtype=np.int16)

    with pytest.raises(ValueError):
        decodificar_muestras(zlib.compress(matriz_ajena.tobytes()))


# --- version_formato: esquema binario, distinta de SenalEcg.version_extractor --


def test_decodificar_muestras_acepta_la_version_de_formato_actual_por_defecto() -> None:
    matriz = _matriz_con(1234)

    assert np.array_equal(decodificar_muestras(codificar_muestras(matriz)), matriz)
    assert np.array_equal(
        decodificar_muestras(codificar_muestras(matriz), version_formato=VERSION_FORMATO_ACTUAL), matriz
    )


def test_decodificar_muestras_rechaza_version_de_formato_desconocida() -> None:
    """Nunca decodifica a ciegas: un `version_formato` que este módulo no
    conoce lanza explícito, aunque los bytes en sí sean válidos para el
    formato actual."""
    matriz = _matriz_con(1234)

    with pytest.raises(ValueError, match="version_formato"):
        decodificar_muestras(codificar_muestras(matriz), version_formato=VERSION_FORMATO_ACTUAL + 1)


def test_decodificar_mascara_rechaza_version_de_formato_desconocida() -> None:
    mascara = np.zeros(FORMA, dtype=bool)

    with pytest.raises(ValueError, match="version_formato"):
        decodificar_mascara(codificar_mascara(mascara), version_formato=999)
