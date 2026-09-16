"""`SenalEcg`: señal de ECG calibrada (12 derivaciones + tira de ritmo).
`eq=False`: comparar `ndarray` con `==` da un array, no un `bool`."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

FORMA = (12, 5000)


@dataclass(frozen=True, eq=False)
class SenalEcg:
    muestras_uv: np.ndarray  # int16 (12, 5000)
    mascara: np.ndarray  # bool (12, 5000)
    frecuencia_hz: int = 500
    # Sin default: obliga a declarar en cada sitio qué versión del algoritmo produjo la señal.
    version_extractor: int = field(kw_only=True)

    def __post_init__(self) -> None:
        if self.muestras_uv.shape != FORMA:
            raise ValueError(f"muestras_uv debe tener forma {FORMA}")
        if self.mascara.shape != FORMA:
            raise ValueError(f"mascara debe tener forma {FORMA}")
        if self.muestras_uv.dtype != np.int16:
            raise ValueError("muestras_uv debe ser int16")
        if self.mascara.dtype != np.bool_:
            raise ValueError("mascara debe ser bool")

    def __repr__(self) -> str:
        filas, columnas = self.muestras_uv.shape
        return f"SenalEcg({filas}x{columnas}@{self.frecuencia_hz}Hz)"
