"""Precisión declarada de `hora_estudio`; no es derivable del valor almacenado."""

from __future__ import annotations

from enum import Enum


class PrecisionHora(str, Enum):
    """Qué tan fina es la hora capturada, o si el documento no la trae."""

    AUSENTE = "ausente"
    MINUTO = "minuto"
    SEGUNDO = "segundo"
