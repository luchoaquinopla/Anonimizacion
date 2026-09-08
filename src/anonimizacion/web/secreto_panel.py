"""Carga del secreto compartido del panel (feature `acceso-al-panel`).

El panel pasó de mostrar sólo lectura a poder lanzar horas de trabajo sobre
cualquier carpeta bajo `--raiz` (`POST /corridas`, feature
`despachador-desde-el-panel`). Este módulo carga el secreto que
`autenticacion_panel.py` exige para cerrar ese hueco.

Deliberadamente SEPARADO de `pseudonimizacion/almacen_pepper.py`, aunque el
patrón sea casi idéntico (dos fuentes con la misma precedencia, mismo
cacheo, mismo "nunca se filtra el valor"): son secretos de naturaleza
distinta que no deben mezclarse ni por accidente de refactor. El pepper HMAC
es el secreto que hace irreversibles las claves de pseudonimización -- si
algún día cambia (rotación, incidente), cualquier `id_paciente` ya generado
se invalida. El secreto del panel es sólo una credencial de acceso a la
interfaz web -- rotarlo no toca un solo dato ya escrito. Compartir el
mismo valor entre los dos acoplaría dos ciclos de vida que no tienen
por qué coincidir (instrucción explícita de la tarea: "el pepper HMAC no
se toca ni se reusa para esto").

Fuentes soportadas, en orden de precedencia (la primera que exista gana):

1. Variable de entorno `ANONIMIZACION_PANEL_SECRETO`.
2. Variable de entorno `ANONIMIZACION_PANEL_SECRETO_ARCHIVO` con la ruta a
   un archivo local (mismo uso que `ANONIMIZACION_PEPPER_ARCHIVO`: alternativa
   simple para desarrollo/on-prem).

Si ninguna fuente está configurada, `obtener_secreto_panel` lanza
`ErrorSecretoPanelNoConfigurado`. Quien decide qué hacer con esa ausencia es
el punto de entrada (`scripts/servir_panel.py`): con `--escuchar-red` es un
arranque fallido (ver `main()`); sirviendo sólo en `127.0.0.1` es tolerado
sin autenticación, para no romper el uso local/de desarrollo que ya existía.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

VAR_ENV_SECRETO = "ANONIMIZACION_PANEL_SECRETO"
VAR_ENV_ARCHIVO_SECRETO = "ANONIMIZACION_PANEL_SECRETO_ARCHIVO"


class ErrorSecretoPanelNoConfigurado(RuntimeError):
    """El secreto del panel no está disponible en ninguna fuente soportada.

    Nunca lleva el valor de ninguna variable/archivo leído -- ni en el
    mensaje ni en ningún atributo -- para que no pueda filtrarse por un
    logger que capture la excepción (mismo criterio que
    `ErrorPepperNoConfigurado`).
    """

    def __init__(self) -> None:
        super().__init__(
            f"Secreto del panel no configurado: definir {VAR_ENV_SECRETO} o {VAR_ENV_ARCHIVO_SECRETO}"
        )

    def __repr__(self) -> str:
        return "ErrorSecretoPanelNoConfigurado()"


@lru_cache(maxsize=1)
def obtener_secreto_panel() -> bytes:
    """Devuelve el secreto cacheado en memoria; lo carga una sola vez.

    En tests, llamar `obtener_secreto_panel.cache_clear()` entre casos para
    que cada uno controle su propio entorno (ver
    `tests/web/test_secreto_panel.py`).
    """
    valor_variable = os.environ.get(VAR_ENV_SECRETO)
    if valor_variable:
        return valor_variable.encode("utf-8")

    ruta_archivo = os.environ.get(VAR_ENV_ARCHIVO_SECRETO)
    if ruta_archivo:
        contenido = Path(ruta_archivo).read_text(encoding="utf-8").strip()
        if contenido:
            return contenido.encode("utf-8")

    raise ErrorSecretoPanelNoConfigurado()
