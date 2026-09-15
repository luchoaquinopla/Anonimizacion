"""Codificación binaria de `SenalEcg` para `senal_ecg` (design.md, decisión 3).

`int16` little-endian + zlib para las muestras (µV, ya calibradas por
`extraccion/senal_ecg.py`); `packbits` + zlib para la máscara. Puramente de
empaquetado: este módulo NUNCA satura ni recorta un valor -- si un valor
fuera de rango llegara acá, sería un bug de `extraccion/senal_ecg.py`
(`SenalEcg.__post_init__` ya exige `dtype == int16`, así que ningún valor
puede llegar fuera de ese rango sin haber sido rechazado antes). La decisión
de aceptar o descartar una señal por su geometría (incluida su amplitud) es
de `extraccion/senal_ecg.py` (rechazo todo-o-nada), no de este codec.
"""

from __future__ import annotations

import zlib

import numpy as np

from ..dominio.senal_ecg import FORMA

_DTYPE_MUESTRAS = np.dtype("<i2")  # int16 little-endian explícito
_CANTIDAD_MUESTRAS = FORMA[0] * FORMA[1]


def codificar_muestras(muestras_uv: np.ndarray) -> bytes:
    return zlib.compress(muestras_uv.astype(_DTYPE_MUESTRAS).tobytes())


def decodificar_muestras(datos: bytes) -> np.ndarray:
    crudo = np.frombuffer(zlib.decompress(datos), dtype=_DTYPE_MUESTRAS)
    if crudo.size != _CANTIDAD_MUESTRAS:
        raise ValueError(f"esperaba {_CANTIDAD_MUESTRAS} muestras, llegaron {crudo.size}")
    return crudo.reshape(FORMA).astype(np.int16)


def codificar_mascara(mascara: np.ndarray) -> bytes:
    return zlib.compress(np.packbits(mascara).tobytes())


def decodificar_mascara(datos: bytes) -> np.ndarray:
    bits = np.frombuffer(zlib.decompress(datos), dtype=np.uint8)
    return np.unpackbits(bits, count=_CANTIDAD_MUESTRAS).astype(bool).reshape(FORMA)
