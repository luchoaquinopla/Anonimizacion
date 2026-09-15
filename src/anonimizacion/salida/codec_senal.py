"""Codificación binaria de `SenalEcg` para `senal_ecg` (design.md, decisión 3).

`int16` little-endian + zlib para las muestras (µV, ya calibradas por
`extraccion/senal_ecg.py`); `packbits` + zlib para la máscara. Puramente de
empaquetado: este módulo NUNCA satura ni recorta un valor. Corrección
(revisión adversarial, CRÍTICO): `SenalEcg.__post_init__` sólo valida
`dtype == int16` y la FORMA del arreglo -- NO valida que ningún valor haya
sido corrompido por un wraparound silencioso ANTES de llegar a ese `dtype`
(p. ej. `np.array([32768.0]).astype(np.int16)` da `-32768` sin avisar). La
garantía real de que ningún valor queda fuera de rango vive en
`extraccion/senal_ecg.py::_muestrear`, que ahora RECHAZA (`None`, nunca
recorta) antes de convertir a `int16` -- ver su docstring. Este módulo sigue
sin saturar/recortar nada: sólo empaqueta bytes de un arreglo que, para
cuando llega acá, ya pasó esa validación.

`version_formato` (WARNING, revisión adversarial): versión del ESQUEMA
BINARIO que produce `codificar_*` (layout de bytes: int16 LE + zlib /
packbits + zlib) -- se guarda en la columna `senal_ecg.version_formato`
(migración `0013`), NUNCA embebida en los bytes. Distinta de
`SenalEcg.version_extractor` (versión del ALGORITMO de reconstrucción de la
señal a partir de los trazos, `extraccion/senal_ecg.py`): dos preguntas
independientes -- "¿cómo se empaquetó el binario?" vs. "¿qué algoritmo
produjo estos valores?" -- que podrían evolucionar en momentos distintos.
`decodificar_*` la reciben y la validan explícitamente: un formato
desconocido lanza, nunca decodifica a ciegas.
"""

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
