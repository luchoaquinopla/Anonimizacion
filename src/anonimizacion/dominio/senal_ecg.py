"""`SenalEcg`: señal de ECG calibrada (12 derivaciones + tira de ritmo).

design.md (`senal-ecg-y-dataset-vinculado`): `eq=False` porque comparar
`ndarray` con `==` devuelve un array booleano, no un `bool` -- comparar dos
`SenalEcg` con `==` sería ambiguo, no un error claro. `__repr__` nunca
vuelca las muestras: son geometría medida del PDF (no PII), pero igual son
datos voluminosos sin valor en un log o traceback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

FORMA = (12, 5000)


@dataclass(frozen=True, eq=False)
class SenalEcg:
    muestras_uv: np.ndarray  # int16 (12, 5000)
    mascara: np.ndarray  # bool (12, 5000)
    frecuencia_hz: int = 500
    # Sin default: la única versión que produce el algoritmo vigente es 2
    # (`extraccion/senal_ecg.py::VERSION_EXTRACTOR`, ver `correccion-
    # orientacion-senal-ecg`) -- un default silencioso a 1 podría colar una
    # señal marcada como si viniera del algoritmo viejo (orientación del
    # tiempo invertida), que está documentado como inválido. Obligar a
    # pasarlo explícito hace visible en cada sitio de construcción qué
    # versión del algoritmo produjo la señal.
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
