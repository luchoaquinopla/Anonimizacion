"""Tests de `SenalEcg` (openspec `senal-ecg-y-dataset-vinculado`)."""

from __future__ import annotations

import numpy as np
import pytest

from anonimizacion.dominio.senal_ecg import SenalEcg


def _matriz(forma: tuple[int, int] = (12, 5000), dtype=np.int16) -> np.ndarray:
    return np.zeros(forma, dtype=dtype)


def test_senal_ecg_valida_construye_con_frecuencia_default() -> None:
    senal = SenalEcg(muestras_uv=_matriz(), mascara=_matriz(dtype=bool), version_extractor=2)

    assert senal.frecuencia_hz == 500
    assert senal.version_extractor == 2


def test_senal_ecg_version_extractor_es_obligatorio() -> None:
    """Sin default (`correccion-orientacion-senal-ecg`): la versión 1 del
    algoritmo quedaba con la orientación del tiempo invertida -- un default
    silencioso podría colar una señal sin declarar qué algoritmo la
    produjo."""
    with pytest.raises(TypeError):
        SenalEcg(muestras_uv=_matriz(), mascara=_matriz(dtype=bool))


def test_senal_ecg_repr_nunca_vuelca_las_muestras() -> None:
    senal = SenalEcg(muestras_uv=_matriz(), mascara=_matriz(dtype=bool), version_extractor=2)

    assert repr(senal) == "SenalEcg(12x5000@500Hz)"


@pytest.mark.parametrize(
    ("muestras_uv", "mascara"),
    [
        (_matriz((11, 5000)), _matriz(dtype=bool)),
        (_matriz(), _matriz((12, 4999), dtype=bool)),
        (_matriz(dtype=np.float32), _matriz(dtype=bool)),
        (_matriz(), _matriz(dtype=np.int16)),
    ],
)
def test_senal_ecg_rechaza_forma_o_dtype_invalido(muestras_uv, mascara) -> None:
    with pytest.raises(ValueError):
        SenalEcg(muestras_uv=muestras_uv, mascara=mascara, version_extractor=2)
