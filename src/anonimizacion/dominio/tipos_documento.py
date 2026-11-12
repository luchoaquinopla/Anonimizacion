"""Clasificación de tipos de documento: uno de los 3 layouts conocidos, o no reconocido."""

from __future__ import annotations

from enum import Enum


class TipoDocumento(str, Enum):
    """Los 3 layouts clínicos conocidos, más el centinela de no reconocido."""

    ECG = "ecg"
    LABORATORIO = "laboratorio"
    ECOCARDIOGRAMA = "ecocardiograma"
    TIPO_NO_RECONOCIDO = "tipo_no_reconocido"
