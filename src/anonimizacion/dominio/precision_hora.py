"""Precisión declarada de `hora_estudio`; no es derivable del valor (design.md, decisión 3).

Un laboratorio a las `08:45` se persiste `08:45:00`, byte a byte idéntico a un
ECG con esa misma hora. Sin este campo, un consumidor no puede distinguir
"la hora es exacta al segundo" de "la hora es exacta al minuto, con el
segundo puesto en cero por convención de almacenamiento" -- ni "el documento
no trae hora" de cualquiera de las dos anteriores. Por eso viaja como dato
propio del dominio, nunca como una función de `hora_estudio`.
"""

from __future__ import annotations

from enum import Enum


class PrecisionHora(str, Enum):
    """Qué tan fina es la hora capturada, o si el documento no la trae."""

    AUSENTE = "ausente"
    MINUTO = "minuto"
    SEGUNDO = "segundo"
