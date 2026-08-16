"""Carga del pepper (spec `patient-pseudonymization`, design.md: "Almacenamiento del pepper").

El pepper es el secreto que hace que las claves HMAC (`claves.py`) sean
irreversibles: sin él, un `id_paciente` no puede deshacerse por fuerza bruta.
Reglas no negociables:

- NUNCA hardcodeado en el repo.
- NUNCA logueado, ni siquiera en un mensaje de error (`ErrorPepperNoConfigurado`
  no incluye ningún valor leído, solo dice "no configurado").
- Se carga UNA sola vez y se cachea en memoria (`obtener_pepper` usa
  `lru_cache`) -- simula "cargado al arrancar el worker" sin depender de un
  framework de arranque concreto.

Fuentes soportadas, en orden de precedencia (la primera que exista gana):

1. Variable de entorno `ANONIMIZACION_PEPPER` -- inyectada por el orquestador
   de secretos del entorno (Vault/KMS en producción).
2. Variable de entorno `ANONIMIZACION_PEPPER_ARCHIVO` con la ruta a un
   archivo local (alternativa simple para desarrollo/on-prem; en producción
   ese archivo debe estar cifrado en reposo y con permisos restringidos --
   eso es responsabilidad de infraestructura, fuera del alcance de este
   módulo, ver design.md "Open Questions").

Si ninguna fuente está configurada, `obtener_pepper` lanza
`ErrorPepperNoConfigurado`: el pipeline no debe arrancar (ni procesar un solo
documento) sin pepper, porque sin él no hay forma de generar claves estables.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

VAR_ENV_PEPPER = "ANONIMIZACION_PEPPER"
VAR_ENV_ARCHIVO_PEPPER = "ANONIMIZACION_PEPPER_ARCHIVO"


class ErrorPepperNoConfigurado(RuntimeError):
    """El pepper no está disponible en ninguna fuente soportada.

    Nunca lleva el valor de ninguna variable/archivo leído -- ni en el
    mensaje ni en ningún atributo -- para que no pueda filtrarse por un
    logger que capture la excepción.
    """

    def __init__(self) -> None:
        super().__init__(
            f"Pepper no configurado: definir {VAR_ENV_PEPPER} o {VAR_ENV_ARCHIVO_PEPPER}"
        )

    def __repr__(self) -> str:
        return "ErrorPepperNoConfigurado()"


@lru_cache(maxsize=1)
def obtener_pepper() -> bytes:
    """Devuelve el pepper cacheado en memoria; lo carga una sola vez.

    En tests, llamar `obtener_pepper.cache_clear()` entre casos para que
    cada uno controle su propio entorno (ver `tests/pseudonimizacion/
    test_almacen_pepper.py`).
    """
    valor_variable = os.environ.get(VAR_ENV_PEPPER)
    if valor_variable:
        return valor_variable.encode("utf-8")

    ruta_archivo = os.environ.get(VAR_ENV_ARCHIVO_PEPPER)
    if ruta_archivo:
        contenido = Path(ruta_archivo).read_text(encoding="utf-8").strip()
        if contenido:
            return contenido.encode("utf-8")

    raise ErrorPepperNoConfigurado()
