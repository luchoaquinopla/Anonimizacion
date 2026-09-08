"""Configuración del operador (`arranque-para-el-instituto`, composition root).

Antes de este módulo, `scripts/procesar_carpeta.py` y `scripts/servir_panel.py`
exponían cada uno su propio `argparse`, cada uno con su propia URL de base por
defecto (duplicada, no compartida) -- un médico sin experiencia en línea de
comandos tenía que recordar banderas distintas para cada script. Este módulo
reemplaza esas banderas sueltas por UN archivo de configuración (`*.toml`,
formato legible sin entrenamiento) con los valores NO secretos que hacían
falta para operar: URL de Postgres, carpeta a procesar, puerto y raíz del
panel, grado de concurrencia.

Los SECRETOS (pepper HMAC, secreto del panel) están deliberadamente FUERA del
esquema de este archivo -- ver `ErrorConfiguracionSecretoEnArchivo`. Sólo
pueden venir de `ANONIMIZACION_PEPPER`/`ANONIMIZACION_PEPPER_ARCHIVO`
(`pseudonimizacion/almacen_pepper.py`) y
`ANONIMIZACION_PANEL_SECRETO`/`ANONIMIZACION_PANEL_SECRETO_ARCHIVO`
(`web/secreto_panel.py`), exactamente como hoy: un archivo de configuración
puede terminar compartido con otra persona o versionado por error -- un
secreto ahí es un secreto filtrado.

Fuente de la ruta del archivo, en orden de precedencia:

1. Argumento explícito (`--config` en la CLI).
2. Variable de entorno `ANONIMIZACION_CONFIG`.
3. `./anonimizacion.toml` (relativo al directorio desde donde se invoca el
   comando) -- si NO existe en esta ruta por defecto, no es un error: se
   usan los valores de producción que ya traían los scripts. Si la ruta
   viene de (1) o (2) y no existe, sí es un error (el operador pidió un
   archivo puntual que no está).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from anonimizacion.trabajadores.despacho_paralelo import grado_de_concurrencia_por_defecto

VAR_ENV_RUTA_CONFIG = "ANONIMIZACION_CONFIG"

RUTA_CONFIG_DEFAULT = Path("anonimizacion.toml")

# Mismo default que `scripts/procesar_carpeta.py::_DB_URL_DEFAULT` y
# `scripts/servir_panel.py::_DB_URL_DEFAULT` -- HOY son literales idénticos
# en los tres lugares porque nadie los desincronizó todavía, no porque estén
# atados entre sí. Este módulo es la única fuente de verdad NUEVA: los
# scripts siguen con la suya propia porque también se pueden invocar solos
# (ver docstring de `anonimizacion.cli`), pero `anonimizacion diagnosticar`/
# `procesar`/`servir` -- el camino real -- siempre resuelven desde acá.
_DB_URL_DEFAULT = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
_PUERTO_DEFAULT = 8000

# Único esquema válido de este archivo -- cualquier otra clave es un error
# fuerte (typo de operador o, peor, un secreto que no debería estar acá).
_CLAVES_VALIDAS = {"db_url", "entrada", "raiz", "puerto", "procesos", "escuchar_red"}

# Nombres que un operador razonablemente escribiría para un secreto. No hace
# falta que sea exhaustivo: es una red de contención adicional sobre el
# allowlist de arriba (que ya rechaza CUALQUIER clave no reconocida) para dar
# un mensaje más específico cuando el error probable es justamente ese.
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
    """Base común de los errores de configuración del operador.

    `anonimizacion.cli` captura esta clase para fallar temprano con un
    mensaje en castellano llano, sin traceback, antes de tocar Postgres ni
    ningún PDF -- mismo criterio que `ErrorPepperNoConfigurado`/
    `ErrorSecretoPanel`.
    """


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

    `entrada=None` significa "no se indicó ninguna carpeta a procesar
    todavía" -- válido para `anonimizacion servir` (no la necesita) o para un
    primer `anonimizacion diagnosticar` antes de decidir qué procesar.
    """

    db_url: str = _DB_URL_DEFAULT
    entrada: Path | None = None
    raiz: Path = field(default_factory=lambda: Path("."))
    puerto: int = _PUERTO_DEFAULT
    procesos: int = field(default_factory=grado_de_concurrencia_por_defecto)
    escuchar_red: bool = False


def _resolver_ruta(ruta: Path | None) -> tuple[Path | None, bool]:
    """Devuelve `(ruta_a_intentar, fue_pedida_explicitamente)`.

    `fue_pedida_explicitamente=True` (argumento o variable de entorno)
    convierte "el archivo no existe" en un error -- `False` (ruta por
    defecto) lo convierte en "usar los valores de producción".
    """
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
    """Carga la configuración del operador desde `ruta` (ver el docstring del
    módulo para la precedencia). Nunca lee ni valida secretos -- ver
    `ErrorConfiguracionSecretoEnArchivo`."""
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
