"""Carga del pepper (secreto que hace irreversibles las claves HMAC de `claves.py`): nunca
hardcodeado ni logueado, se cachea una sola vez. Sin pepper configurado, el pipeline no arranca."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

VAR_ENV_PEPPER = "ANONIMIZACION_PEPPER"
VAR_ENV_ARCHIVO_PEPPER = "ANONIMIZACION_PEPPER_ARCHIVO"


class ErrorPepperNoConfigurado(RuntimeError):
    """El pepper no está disponible en ninguna fuente soportada. Nunca lleva el valor de
    ninguna variable/archivo leído, para que no pueda filtrarse por un logger."""

    def __init__(self) -> None:
        super().__init__(
            f"Pepper no configurado: definir {VAR_ENV_PEPPER} o {VAR_ENV_ARCHIVO_PEPPER}"
        )

    def __repr__(self) -> str:
        return "ErrorPepperNoConfigurado()"


@lru_cache(maxsize=1)
def obtener_pepper() -> bytes:
    """Devuelve el pepper cacheado en memoria; lo carga una sola vez. En tests, llamar
    `obtener_pepper.cache_clear()` entre casos para controlar el entorno."""
    valor_variable = os.environ.get(VAR_ENV_PEPPER)
    if valor_variable:
        return valor_variable.encode("utf-8")

    ruta_archivo = os.environ.get(VAR_ENV_ARCHIVO_PEPPER)
    if ruta_archivo:
        contenido = Path(ruta_archivo).read_text(encoding="utf-8").strip()
        if contenido:
            return contenido.encode("utf-8")

    raise ErrorPepperNoConfigurado()
