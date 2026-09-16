"""Carga del secreto compartido del panel. Deliberadamente separado de
`pseudonimizacion/almacen_pepper.py`: son secretos de ciclo de vida distinto (el pepper
HMAC invalida claves de pseudonimización si rota; este sólo es una credencial de acceso)."""

# Fuentes por precedencia: ANONIMIZACION_PANEL_SECRETO, luego
# ANONIMIZACION_PANEL_SECRETO_ARCHIVO. Ambas se recortan antes de validar; un valor no
# vacío que recorta a inválido es error FUERTE, no "no configurado" -- sólo un archivo
# de cero bytes cuenta como fuente ausente. Sin límite de intentos (ver autenticacion_panel.py):
# el piso de longitud ya cierra fuerza bruta en línea, y un contador en memoria de un
# solo proceso se pierde en cada reinicio.

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

VAR_ENV_SECRETO = "ANONIMIZACION_PANEL_SECRETO"
VAR_ENV_ARCHIVO_SECRETO = "ANONIMIZACION_PANEL_SECRETO_ARCHIVO"

# Sólo importa la LONGITUD, no reglas de complejidad: 16 caracteres al azar ya
# vuelven inviable la fuerza bruta en línea sin necesitar limitador de intentos.
LONGITUD_MINIMA_SECRETO = 16


class ErrorSecretoPanel(RuntimeError):
    """Base común de los errores de configuración del secreto del panel.
    El punto de entrada la captura para fallar temprano antes de conectar a Postgres."""


class ErrorSecretoPanelNoConfigurado(ErrorSecretoPanel):
    """Ninguna fuente está configurada. Nunca lleva el valor leído, para que no se
    filtre por un logger que capture la excepción."""

    def __init__(self) -> None:
        super().__init__(
            f"Secreto del panel no configurado: definir {VAR_ENV_SECRETO} o {VAR_ENV_ARCHIVO_SECRETO}"
        )

    def __repr__(self) -> str:
        return "ErrorSecretoPanelNoConfigurado()"


class ErrorSecretoPanelInvalido(ErrorSecretoPanel):
    """Una fuente está configurada pero no alcanza `LONGITUD_MINIMA_SECRETO`.
    Nunca lleva el valor inválido: un secreto corto sigue siendo un secreto."""

    def __init__(self) -> None:
        super().__init__(
            "Secreto del panel invalido: tiene que tener al menos "
            f"{LONGITUD_MINIMA_SECRETO} caracteres despues de recortar espacios en "
            f"blanco -- revisar la fuente configurada ({VAR_ENV_SECRETO} o {VAR_ENV_ARCHIVO_SECRETO})"
        )

    def __repr__(self) -> str:
        return "ErrorSecretoPanelInvalido()"


class ErrorSecretoPanelArchivoIlegible(ErrorSecretoPanel):
    """`ANONIMIZACION_PANEL_SECRETO_ARCHIVO` apunta a una ruta ilegible.
    Incluye la ruta (no es secreta) pero nunca el contenido del archivo."""

    def __init__(self, ruta: str) -> None:
        self._ruta = ruta
        super().__init__(
            f"No se pudo leer el archivo de {VAR_ENV_ARCHIVO_SECRETO} ({ruta}): "
            "revisar que la ruta exista y sea legible."
        )

    def __repr__(self) -> str:
        return f"ErrorSecretoPanelArchivoIlegible({self._ruta!r})"


def _validar(valor: str) -> bytes:
    """Recorta espacios y aplica el piso mínimo de longitud. Punto único de
    validación para las dos fuentes."""
    if len(valor) < LONGITUD_MINIMA_SECRETO:
        raise ErrorSecretoPanelInvalido()
    return valor.encode("utf-8")


@lru_cache(maxsize=1)
def obtener_secreto_panel() -> bytes:
    """Devuelve el secreto cacheado en memoria; lo carga una sola vez. En tests, llamar
    `.cache_clear()` entre casos."""
    valor_variable = os.environ.get(VAR_ENV_SECRETO)
    if valor_variable:
        return _validar(valor_variable.strip())

    ruta_archivo = os.environ.get(VAR_ENV_ARCHIVO_SECRETO)
    if ruta_archivo:
        try:
            contenido_crudo = Path(ruta_archivo).read_text(encoding="utf-8")
        except OSError as error:
            # Sin este try, una ruta mal configurada revienta con un OSError crudo.
            raise ErrorSecretoPanelArchivoIlegible(ruta_archivo) from error
        if contenido_crudo:
            return _validar(contenido_crudo.strip())

    raise ErrorSecretoPanelNoConfigurado()
