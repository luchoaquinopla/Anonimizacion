"""Registro de firmas: una por cada tipo de documento conocido.

Cada layout nuevo se suma acá (un módulo + una entrada en `FIRMAS`); el
detector (`detector_tipo.py`) no cambia.
"""

from __future__ import annotations

from .base import Firma
from .eco_doppler import FIRMA as _FIRMA_ECO
from .ecg_mortara import FIRMA as _FIRMA_ECG
from .laboratorio import FIRMA as _FIRMA_LABORATORIO

FIRMAS: tuple[Firma, ...] = (_FIRMA_ECG, _FIRMA_LABORATORIO, _FIRMA_ECO)

__all__ = ["Firma", "FIRMAS"]
