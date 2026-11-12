"""Asistente de primer arranque: verifica pepper, secreto, Postgres, migraciones y carpeta.
Cada chequeo devuelve un `Hallazgo` en castellano llano, nunca un traceback ni un secreto."""

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
    """`make_url` vive DENTRO del `try`: una URL mal escrita no debe propagar traceback crudo."""
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
    """Detecta más de un head en el REPOSITORIO antes de comparar contra la base."""
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
    """Recupera sola una corrida sin evidencia reciente (>15 min) antes de reportarla trabada.
    `ahora` inyectable para tests, default reloj real."""
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
    """Corre todos los chequeos y devuelve todos los hallazgos, no uno a la vez.
    Migraciones sólo se verifican si la base respondió."""
    hallazgos = [_diagnosticar_pepper(), _diagnosticar_secreto_panel(requiere_red=requiere_red)]

    hallazgo_db, base_responde = _diagnosticar_conexion_db(config.db_url)
    hallazgos.append(hallazgo_db)
    if base_responde:
        hallazgos.append(_diagnosticar_migraciones(config.db_url))
        hallazgos.append(_diagnosticar_corrida_activa(config.db_url))

    if requiere_entrada:
        hallazgos.append(_diagnosticar_carpeta_entrada(config.entrada))

    return hallazgos
