"""Clasificación de tipos de documento.

Ver spec `document-type-detection`: el sistema MUST clasificar un documento
como uno de los 3 layouts conocidos, o marcarlo como no reconocido sin forzar
un parser por defecto.
"""

from __future__ import annotations

from enum import Enum


class TipoDocumento(str, Enum):
    """Los 3 layouts clínicos conocidos, más el centinela de no reconocido."""

    ECG = "ecg"
    LABORATORIO = "laboratorio"
    ECOCARDIOGRAMA = "ecocardiograma"
    TIPO_NO_RECONOCIDO = "tipo_no_reconocido"
