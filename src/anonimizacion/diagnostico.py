"""Asistente de primer arranque (`arranque-para-el-instituto`).

Un médico sin experiencia en línea de comandos no puede interpretar un
traceback de SQLAlchemy ni de `argparse`. Este módulo verifica, ANTES de
tocar un solo PDF, todo lo que hoy fallaba a mitad de una corrida o disfrazado
de otro error:

- el pepper HMAC (`pseudonimizacion/almacen_pepper.py`),
- el secreto del panel, sólo si hace falta (`web/secreto_panel.py`),
- que Postgres esté encendido y accesible,
- que las migraciones de Alembic estén al día (y detecta cuando el propio
  repositorio tiene más de una migración 'head' a la vez, un problema del
  código, no de la base),
- que no haya una corrida trabada bloqueando el gate de "una corrida a la
  vez" -- recupera sola una corrida abandonada (sin evidencia reciente,
  misma lógica que `servir_panel.py` usa en cada arranque) en vez de pedirle
  al operador que espere algo que no va a terminar,
- que la carpeta a procesar exista, sea una carpeta y se pueda leer.

Cada chequeo devuelve un `Hallazgo` con un mensaje en castellano llano: qué
pasó y qué hacer -- nunca un traceback, nunca el valor de un secreto (mismo
criterio que `web/codigos_cuarentena.py`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from anonimizacion.configuracion import ConfiguracionOperador
from anonimizacion.ingesta.lanzador_corrida import recuperar_corridas_abandonadas
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.pseudonimizacion.almacen_pepper import ErrorPepperNoConfigurado, obtener_pepper
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.web.secreto_panel import ErrorSecretoPanel, ErrorSecretoPanelNoConfigurado, obtener_secreto_panel

_RAIZ_REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Hallazgo:
    ok: bool
    mensaje: str


def _diagnosticar_pepper() -> Hallazgo:
    try:
        obtener_pepper()
    except ErrorPepperNoConfigurado as error:
        return Hallazgo(False, f"Pepper: {error}")
    return Hallazgo(True, "Pepper: configurado.")


def _diagnosticar_secreto_panel(*, requiere_red: bool) -> Hallazgo:
    try:
        obtener_secreto_panel()
    except ErrorSecretoPanelNoConfigurado:
        if requiere_red:
            return Hallazgo(
                False,
                "Secreto del panel: no configurado. Es obligatorio para exponer el panel "
                "a la red del instituto -- definir ANONIMIZACION_PANEL_SECRETO o "
                "ANONIMIZACION_PANEL_SECRETO_ARCHIVO antes de usar --escuchar-red.",
            )
        return Hallazgo(
            True,
            "Secreto del panel: no configurado (no hace falta -- el panel sólo va a "
            "escuchar en esta máquina).",
        )
    except ErrorSecretoPanel as error:
        return Hallazgo(False, f"Secreto del panel: {error}")
    return Hallazgo(True, "Secreto del panel: configurado.")


def _diagnosticar_conexion_db(db_url: str) -> tuple[Hallazgo, bool]:
    """Revisión adversarial, CRÍTICO 2: `make_url(db_url)` ANTES vivía fuera
    de este `try` -- una URL mal escrita en el archivo de configuración
    (falta el driver, faltan las "//", etc.) hacía que
    `sqlalchemy.exc.ArgumentError` se propagara crudo, con traceback completo
    y rutas de `site-packages`, en los tres subcomandos (los tres llaman a
    `diagnosticar()` antes de cualquier otra cosa). `url_para_mostrar`
    arranca en el propio `db_url` sin procesar -- si ni siquiera se puede
    interpretar como URL, no hay estructura de credenciales que enmascarar:
    mostrar el texto tal cual no filtra nada que el operador no haya
    escrito él mismo en su propio archivo."""
    url_para_mostrar = db_url
    engine = None
    try:
        url_para_mostrar = make_url(db_url).render_as_string(hide_password=True)
        engine = construir_engine_postgres(db_url)
        with engine.connect() as conexion:
            conexion.execute(sa.text("SELECT 1"))
    except Exception as error:  # noqa: BLE001 -- cualquier fallo (URL invalida, host caido, credenciales) es "no se pudo conectar"
        return (
            Hallazgo(
                False,
                f"Base de datos: no se pudo conectar a '{url_para_mostrar}'. Verificar que "
                "Postgres esté encendido y accesible desde esta máquina, y que la URL en "
                f"la configuración sea correcta. Detalle técnico: {type(error).__name__}.",
            ),
            False,
        )
    finally:
        if engine is not None:
            engine.dispose()
    return Hallazgo(True, "Base de datos: conexión correcta."), True


def _diagnosticar_migraciones(db_url: str) -> Hallazgo:
    """Revisión adversarial, MAYOR 4 -- reproducido con dos heads reales
    (este repositorio tuvo, a la vez, `migrations/versions/0009_corrida_una_activa.py`
    en `main` y un `0009_episodio_tipo_unico.py` en otra rama): antes de este
    cambio, dos heads en el REPOSITORIO (no en la base) se confundían con
    "la base no tiene las últimas migraciones", y la instrucción sugerida
    (`alembic upgrade head`) fallaba con otro error ('Multiple head revisions
    are present'), en inglés, sin ninguna pista de que el problema real es
    del código, no de esta base. Esto se verifica ANTES de tocar la base:
    con dos heads, ningún estado de la base puede estar "al día" -- la
    pregunta ni siquiera tiene sentido todavía."""
    try:
        cfg = Config(str(_RAIZ_REPO / "alembic.ini"))
        cfg.set_main_option("script_location", str(_RAIZ_REPO / "migrations"))
        cfg.set_main_option("sqlalchemy.url", db_url)
        script = ScriptDirectory.from_config(cfg)
        heads_esperados = set(script.get_heads())
    except Exception as error:  # noqa: BLE001 -- no se pudo leer el directorio de migraciones
        return Hallazgo(False, f"Migraciones: no se pudo verificar su estado. Detalle técnico: {error}")

    if len(heads_esperados) > 1:
        cabezas = ", ".join(sorted(heads_esperados))
        return Hallazgo(
            False,
            f"Migraciones: el repositorio tiene más de una migración 'head' a la vez ({cabezas}). "
            "Esto es un problema del código instalado, no de esta base de datos -- avisar a quien "
            "mantiene el repositorio. 'alembic upgrade head' no va a funcionar hasta que alguien "
            "una esas migraciones (alembic merge heads).",
        )

    try:
        engine = construir_engine_postgres(db_url)
        try:
            with engine.connect() as conexion:
                contexto = MigrationContext.configure(conexion)
                heads_actuales = set(contexto.get_current_heads())
        finally:
            engine.dispose()
    except Exception as error:  # noqa: BLE001 -- no se pudo determinar el estado, no asumir nada
        return Hallazgo(False, f"Migraciones: no se pudo verificar su estado. Detalle técnico: {error}")

    if heads_actuales != heads_esperados:
        return Hallazgo(
            False,
            "Migraciones: la base de datos no tiene aplicadas las últimas migraciones. "
            "Ejecutar: alembic upgrade head",
        )
    return Hallazgo(True, "Migraciones: al día.")


def _diagnosticar_corrida_activa(db_url: str, *, ahora: datetime | None = None) -> Hallazgo:
    """Revisión adversarial, CRÍTICO 1: `scripts/procesar_carpeta.py` no
    cerraba sus corridas (arreglado en el mismo cambio), y el gate de "una
    corrida a la vez" (`ux_corrida_una_activa`) puede quedar trabado por
    CUALQUIER causa externa a este comando -- un `kill -9`, un corte de luz,
    un proceso que quedó colgado. Antes de reportar, se reutiliza la MISMA
    lógica que `servir_panel.py` ya usa en cada arranque
    (`recuperar_corridas_abandonadas`): una corrida sin evidencia reciente
    (>15 min, `MARGEN_INACTIVIDAD_DEFAULT`) se cierra sola como `FALLIDA` --
    no tiene sentido decirle al operador "esperá a que termine" algo que ya
    no va a terminar. Sólo una corrida con evidencia RECIENTE (genuinamente
    en curso, en el panel o en otra invocación de este mismo comando) se
    reporta como error -- y ahí sí es honesto pedir que se espere.

    `ahora` (default `None` = reloj real): mismo patrón inyectable que
    `recuperar_corridas_abandonadas`, sólo para que los tests puedan simular
    una corrida abandonada sin dormir 15 minutos de verdad.
    """
    engine = None
    try:
        engine = construir_engine_postgres(db_url)
        repositorio = RepositorioCorridas(engine)
        recuperar_corridas_abandonadas(repositorio, ahora=ahora)
        activas = repositorio.listar_corridas_no_terminales()
    except Exception as error:  # noqa: BLE001 -- no se pudo verificar, no asumir nada
        return Hallazgo(False, f"Corrida activa: no se pudo verificar. Detalle técnico: {error}")
    finally:
        if engine is not None:
            engine.dispose()

    if not activas:
        return Hallazgo(True, "Corrida activa: ninguna -- se puede lanzar una corrida nueva.")

    ids = ", ".join(corrida.id_corrida for corrida in activas)
    return Hallazgo(
        False,
        f"Corrida activa: '{ids}' tiene actividad reciente (menos de 15 minutos) -- esperar "
        "a que termine, o revisar el panel/proceso que la está corriendo, antes de lanzar otra.",
    )


def _diagnosticar_carpeta_entrada(entrada: Path | None) -> Hallazgo:
    if entrada is None:
        return Hallazgo(
            False,
            "Carpeta a procesar: no se indicó ninguna. Agregar --entrada en el comando, "
            "o la clave 'entrada' en el archivo de configuración.",
        )
    if not entrada.exists():
        return Hallazgo(False, f"Carpeta a procesar: '{entrada}' no existe. Verificar la ruta.")
    if not entrada.is_dir():
        return Hallazgo(False, f"Carpeta a procesar: '{entrada}' no es una carpeta.")
    if not os.access(entrada, os.R_OK):
        return Hallazgo(False, f"Carpeta a procesar: '{entrada}' no se puede leer. Verificar los permisos.")
    return Hallazgo(True, f"Carpeta a procesar: '{entrada}' accesible.")


def diagnosticar(
    config: ConfiguracionOperador, *, requiere_entrada: bool, requiere_red: bool
) -> list[Hallazgo]:
    """Corre todos los chequeos aplicables y devuelve TODOS los hallazgos --
    ok y error -- para que el operador vea de una vez todo lo que falta, no
    un problema a la vez en sucesivas corridas fallidas.

    Las migraciones sólo se verifican si la base respondió: sin conexión no
    hay forma de saber su estado, y reportarlo como error aparte sólo
    duplicaría el mensaje de "Base de datos" con otro peor (una excepción de
    conexión disfrazada de problema de migraciones).
    """
    hallazgos = [_diagnosticar_pepper(), _diagnosticar_secreto_panel(requiere_red=requiere_red)]

    hallazgo_db, base_responde = _diagnosticar_conexion_db(config.db_url)
    hallazgos.append(hallazgo_db)
    if base_responde:
        hallazgos.append(_diagnosticar_migraciones(config.db_url))
        hallazgos.append(_diagnosticar_corrida_activa(config.db_url))

    if requiere_entrada:
        hallazgos.append(_diagnosticar_carpeta_entrada(config.entrada))

    return hallazgos
