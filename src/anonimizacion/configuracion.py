"""Configuración del operador: valores NO secretos para operar el pipeline (`*.toml`).
Precedencia de ruta: `--config` explícito > `ANONIMIZACION_CONFIG` > `./anonimizacion.toml`."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from anonimizacion.trabajadores.despacho_paralelo import grado_de_concurrencia_por_defecto

VAR_ENV_RUTA_CONFIG = "ANONIMIZACION_CONFIG"

RUTA_CONFIG_DEFAULT = Path("anonimizacion.toml")

# Única fuente de este valor; comandos/procesar.py y comandos/servir.py lo importan de acá.
_DB_URL_DEFAULT = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
_PUERTO_DEFAULT = 8000

# Único esquema válido de este archivo; cualquier otra clave es un error fuerte.
_CLAVES_VALIDAS = {"db_url", "entrada", "raiz", "puerto", "procesos", "escuchar_red"}

# Red de contención adicional sobre _CLAVES_VALIDAS para dar un mensaje más específico.
_CLAVES_DE_SECRETOS = {
    "pepper",
    "secreto",
    "secret",
    "password",
    "contrasena",
    "contraseña",
    "token",
    "anonimizacion_pepper",
    "anonimizacion_panel_secreto",
}


class ErrorConfiguracion(RuntimeError):
    """Base común; `cli.py` la captura para fallar temprano sin traceback."""


class ErrorConfiguracionNoEncontrada(ErrorConfiguracion):
    def __init__(self, ruta: Path) -> None:
        super().__init__(
            f"No se encontró el archivo de configuración en '{ruta}'. "
            "Verificar la ruta, o crear el archivo a partir del ejemplo "
            "(ver deploy/anonimizacion.toml.example)."
        )


class ErrorConfiguracionInvalida(ErrorConfiguracion):
    def __init__(self, ruta: Path, motivo: str) -> None:
        super().__init__(
            f"El archivo de configuración '{ruta}' tiene un error de sintaxis y no "
            f"se pudo leer ({motivo}). Revisar comillas, corchetes y el signo '=' de "
            "cada línea."
        )


class ErrorConfiguracionSecretoEnArchivo(ErrorConfiguracion):
    def __init__(self, clave: str, ruta: Path) -> None:
        super().__init__(
            f"La clave '{clave}' en '{ruta}' parece un secreto. Los secretos (el pepper "
            "del pipeline, el secreto del panel) nunca van en este archivo -- van en una "
            "variable de entorno (ANONIMIZACION_PEPPER, ANONIMIZACION_PANEL_SECRETO) o en "
            "un archivo aparte con permisos restringidos (ANONIMIZACION_PEPPER_ARCHIVO, "
            f"ANONIMIZACION_PANEL_SECRETO_ARCHIVO). Sacar '{clave}' de '{ruta}' y "
            "configurarlo por esa vía."
        )


class ErrorConfiguracionClaveDesconocida(ErrorConfiguracion):
    def __init__(self, clave: str, ruta: Path) -> None:
        claves_validas = ", ".join(sorted(_CLAVES_VALIDAS))
        super().__init__(
            f"La clave '{clave}' en '{ruta}' no es una opción reconocida (¿un error de "
            f"tipeo?). Claves válidas: {claves_validas}."
        )


class ErrorConfiguracionTipoInvalido(ErrorConfiguracion):
    def __init__(self, clave: str, valor: object, ruta: Path, tipo_esperado: str) -> None:
        super().__init__(
            f"La clave '{clave}' en '{ruta}' tiene un valor inválido ({valor!r}); "
            f"se esperaba {tipo_esperado}."
        )


@dataclass(frozen=True)
class ConfiguracionOperador:
    """Valores NO secretos que hacen falta para operar el pipeline.
    `entrada=None`: no se indicó ninguna carpeta a procesar todavía."""

    db_url: str = _DB_URL_DEFAULT
    entrada: Path | None = None
    raiz: Path = field(default_factory=lambda: Path("."))
    puerto: int = _PUERTO_DEFAULT
    procesos: int = field(default_factory=grado_de_concurrencia_por_defecto)
    escuchar_red: bool = False


def _resolver_ruta(ruta: Path | None) -> tuple[Path | None, bool]:
    """Devuelve `(ruta_a_intentar, fue_pedida_explicitamente)`; explícita = error si no existe."""
    if ruta is not None:
        return ruta, True

    ruta_de_entorno = os.environ.get(VAR_ENV_RUTA_CONFIG)
    if ruta_de_entorno:
        return Path(ruta_de_entorno), True

    return RUTA_CONFIG_DEFAULT, False


def _convertir_puerto(valor: object, ruta: Path) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorConfiguracionTipoInvalido("puerto", valor, ruta, "un número entero de puerto TCP")
    return valor


def _convertir_procesos(valor: object, ruta: Path) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorConfiguracionTipoInvalido("procesos", valor, ruta, "un número entero de procesos")
    return valor


def _convertir_bool(clave: str, valor: object, ruta: Path) -> bool:
    if not isinstance(valor, bool):
        raise ErrorConfiguracionTipoInvalido(clave, valor, ruta, "verdadero o falso (true/false, sin comillas)")
    return valor


def _convertir_texto(clave: str, valor: object, ruta: Path) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorConfiguracionTipoInvalido(clave, valor, ruta, "un texto no vacío")
    return valor


def _convertir_ruta(clave: str, valor: object, ruta: Path) -> Path:
    return Path(_convertir_texto(clave, valor, ruta))


def _validar_claves(datos: dict, ruta: Path) -> None:
    for clave in datos:
        if clave.lower() in _CLAVES_DE_SECRETOS:
            raise ErrorConfiguracionSecretoEnArchivo(clave, ruta)
        if clave not in _CLAVES_VALIDAS:
            raise ErrorConfiguracionClaveDesconocida(clave, ruta)


def cargar_configuracion(ruta: Path | None = None) -> ConfiguracionOperador:
    """Carga la configuración del operador desde `ruta`. Nunca lee ni valida secretos."""
    ruta_a_intentar, es_explicita = _resolver_ruta(ruta)
    assert ruta_a_intentar is not None  # _resolver_ruta siempre devuelve una ruta concreta

    if not ruta_a_intentar.exists():
        if es_explicita:
            raise ErrorConfiguracionNoEncontrada(ruta_a_intentar)
        return ConfiguracionOperador()

    try:
        contenido = ruta_a_intentar.read_text(encoding="utf-8")
        datos = tomllib.loads(contenido)
    except tomllib.TOMLDecodeError as error:
        raise ErrorConfiguracionInvalida(ruta_a_intentar, str(error)) from error

    _validar_claves(datos, ruta_a_intentar)

    base = ConfiguracionOperador()
    return ConfiguracionOperador(
        db_url=_convertir_texto("db_url", datos["db_url"], ruta_a_intentar) if "db_url" in datos else base.db_url,
        entrada=_convertir_ruta("entrada", datos["entrada"], ruta_a_intentar) if "entrada" in datos else base.entrada,
        raiz=_convertir_ruta("raiz", datos["raiz"], ruta_a_intentar) if "raiz" in datos else base.raiz,
        puerto=_convertir_puerto(datos["puerto"], ruta_a_intentar) if "puerto" in datos else base.puerto,
        procesos=_convertir_procesos(datos["procesos"], ruta_a_intentar) if "procesos" in datos else base.procesos,
        escuchar_red=(
            _convertir_bool("escuchar_red", datos["escuchar_red"], ruta_a_intentar)
            if "escuchar_red" in datos
            else base.escuchar_red
        ),
    )
