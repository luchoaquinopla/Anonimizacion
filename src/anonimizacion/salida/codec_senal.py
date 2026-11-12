"""Codificación binaria de `SenalEcg`: int16 LE + zlib para muestras, packbits + zlib para la
máscara. Puramente de empaquetado -- nunca satura/recorta; esa garantía vive en `extraccion/
senal_ecg.py::_muestrear`. `version_formato` es del esquema binario, distinta de
`version_extractor` (algoritmo de reconstrucción); un formato desconocido lanza, nunca decodifica a ciegas."""

from __future__ import annotations

import zlib

import numpy as np

from ..dominio.senal_ecg import FORMA

_DTYPE_MUESTRAS = np.dtype("<i2")  # int16 little-endian explícito
_CANTIDAD_MUESTRAS = FORMA[0] * FORMA[1]

VERSION_FORMATO_ACTUAL = 1


def _validar_version_formato(version_formato: int) -> None:
    if version_formato != VERSION_FORMATO_ACTUAL:
        raise ValueError(
            f"version_formato desconocida: {version_formato} (soportada: {VERSION_FORMATO_ACTUAL})"
        )


def codificar_muestras(muestras_uv: np.ndarray) -> bytes:
    return zlib.compress(muestras_uv.astype(_DTYPE_MUESTRAS).tobytes())


def decodificar_muestras(datos: bytes, *, version_formato: int = VERSION_FORMATO_ACTUAL) -> np.ndarray:
    _validar_version_formato(version_formato)
    crudo = np.frombuffer(zlib.decompress(datos), dtype=_DTYPE_MUESTRAS)
    if crudo.size != _CANTIDAD_MUESTRAS:
        raise ValueError(f"esperaba {_CANTIDAD_MUESTRAS} muestras, llegaron {crudo.size}")
    return crudo.reshape(FORMA).astype(np.int16)


def codificar_mascara(mascara: np.ndarray) -> bytes:
    return zlib.compress(np.packbits(mascara).tobytes())


def decodificar_mascara(datos: bytes, *, version_formato: int = VERSION_FORMATO_ACTUAL) -> np.ndarray:
    _validar_version_formato(version_formato)
    bits = np.frombuffer(zlib.decompress(datos), dtype=np.uint8)
    return np.unpackbits(bits, count=_CANTIDAD_MUESTRAS).astype(bool).reshape(FORMA)
