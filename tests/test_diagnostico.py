"""Tests de `anonimizacion.diagnostico` (asistente de primer arranque,
`arranque-para-el-instituto`).

Cada chequeo tiene que devolver un mensaje en castellano llano que diga QUÉ
pasó y QUÉ hacer -- nunca un traceback ni un valor de secreto leído (mismo
criterio que `web/codigos_cuarentena.py` y `pseudonimizacion/almacen_pepper.py`).
"""

from __future__ import annotations

import socket

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from anonimizacion.configuracion import ConfiguracionOperador
from anonimizacion.diagnostico import diagnosticar
from anonimizacion.pseudonimizacion.almacen_pepper import obtener_pepper
from anonimizacion.web.secreto_panel import obtener_secreto_panel

_RAIZ_REPO_ALEMBIC = Config(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "alembic.ini"))
_URL_POSTGRES_REAL = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
_URL_POSTGRES_ADMIN = _URL_POSTGRES_REAL
_NOMBRE_BASE_SCRATCH_DIAGNOSTICO = "diagnostico_scratch_test"
_CONNECT_REAL = socket.socket.connect


@pytest.fixture(autouse=True)
def _limpiar_caches_de_secretos(monkeypatch: pytest.MonkeyPatch):
    obtener_pepper.cache_clear()
    obtener_secreto_panel.cache_clear()
    monkeypatch.delenv("ANONIMIZACION_PEPPER", raising=False)
    monkeypatch.delenv("ANONIMIZACION_PEPPER_ARCHIVO", raising=False)
    monkeypatch.delenv("ANONIMIZACION_PANEL_SECRETO", raising=False)
    monkeypatch.delenv("ANONIMIZACION_PANEL_SECRETO_ARCHIVO", raising=False)
    yield
    obtener_pepper.cache_clear()
    obtener_secreto_panel.cache_clear()


def _mensaje(hallazgos, prefijo: str) -> str:
    (hallazgo,) = [h for h in hallazgos if h.mensaje.startswith(prefijo)]
    return hallazgo.mensaje


def _ok(hallazgos, prefijo: str) -> bool:
    (hallazgo,) = [h for h in hallazgos if h.mensaje.startswith(prefijo)]
    return hallazgo.ok


def test_reporta_pepper_faltante_con_mensaje_util(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ConfiguracionOperador(db_url="sqlite:///:memory:")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Pepper") is False
    assert "ANONIMIZACION_PEPPER" in _mensaje(hallazgos, "Pepper")


def test_reporta_pepper_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANONIMIZACION_PEPPER", "pepper-de-prueba-nunca-real")
    config = ConfiguracionOperador(db_url="sqlite:///:memory:")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Pepper") is True


def test_secreto_del_panel_ausente_sin_exponer_a_la_red_no_es_error() -> None:
    config = ConfiguracionOperador(db_url="sqlite:///:memory:")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Secreto del panel") is True


def test_secreto_del_panel_ausente_exponiendo_a_la_red_es_error() -> None:
    config = ConfiguracionOperador(db_url="sqlite:///:memory:")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=True)

    assert _ok(hallazgos, "Secreto del panel") is False


def test_secreto_del_panel_invalido_es_error_aunque_no_se_exponga_a_la_red(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANONIMIZACION_PANEL_SECRETO", "corto")
    config = ConfiguracionOperador(db_url="sqlite:///:memory:")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Secreto del panel") is False


def test_reporta_conexion_a_base_correcta_con_sqlite_en_memoria() -> None:
    config = ConfiguracionOperador(db_url="sqlite:///:memory:")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Base de datos") is True


def test_reporta_conexion_a_base_fallida_con_mensaje_util() -> None:
    """Base apagada/URL mal escrita: el mensaje tiene que decir qué hacer,
    no dejar pasar un traceback de SQLAlchemy/psycopg."""
    config = ConfiguracionOperador(db_url="postgresql+psycopg://usuario:clave@host-que-no-existe:5433/db")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Base de datos") is False
    mensaje = _mensaje(hallazgos, "Base de datos")
    assert "no se pudo conectar" in mensaje.lower()
    assert "clave" not in mensaje, "no debe filtrar la contraseña de la URL de conexión"


def test_url_de_base_mal_escrita_no_deja_pasar_una_traza_cruda() -> None:
    """Revisión adversarial, CRÍTICO 2 -- reproducido con `--db-url
    "esto-no-es-una-url"`: `make_url(...)` corría ANTES del `try` en
    `_diagnosticar_conexion_db`, así que `sqlalchemy.exc.ArgumentError` se
    propagaba crudo -- traceback completo con rutas de site-packages -- en
    los tres subcomandos (`diagnosticar`, `procesar`, `servir`, los tres
    llaman a `diagnosticar()` primero). `diagnosticar` nunca debe lanzar: el
    problema tiene que volver como un `Hallazgo` en la lista, igual que
    cualquier otro fallo de conexión."""
    config = ConfiguracionOperador(db_url="esto-no-es-una-url")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)  # no debe lanzar

    assert _ok(hallazgos, "Base de datos") is False
    mensaje = _mensaje(hallazgos, "Base de datos")
    assert "no se pudo conectar" in mensaje.lower()
    assert "Traceback" not in mensaje


def test_no_verifica_migraciones_si_la_base_no_responde() -> None:
    config = ConfiguracionOperador(db_url="postgresql+psycopg://usuario:clave@host-que-no-existe:5433/db")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert not any(h.mensaje.startswith("Migraciones") for h in hallazgos)


def test_multiples_heads_de_alembic_da_una_instruccion_que_sirve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revisión adversarial, MAYOR 4 -- reproducido con dos heads reales:
    antes esta rama nunca se distinguía de "desactualizada" y `diagnostico`
    recomendaba 'alembic upgrade head', que con dos heads falla con OTRO
    error ('Multiple head revisions are present'), en inglés, sin ninguna
    pista de que el problema real es del repositorio (dos migraciones que
    necesitan un `alembic merge`), no de esta base de datos."""

    class _ScriptDirectoryFalso:
        def get_heads(self):
            return ["0009_corrida_una_activa", "0009_episodio_tipo_unico"]

    monkeypatch.setattr(
        "anonimizacion.diagnostico.ScriptDirectory.from_config", lambda cfg: _ScriptDirectoryFalso()
    )
    config = ConfiguracionOperador(db_url="sqlite:///:memory:")

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Migraciones") is False
    mensaje = _mensaje(hallazgos, "Migraciones")
    assert "0009_corrida_una_activa" in mensaje and "0009_episodio_tipo_unico" in mensaje
    assert "merge" in mensaje.lower(), "tiene que instruir a unir las migraciones, no repetir 'upgrade head' sin mas"
    assert "no va a funcionar" in mensaje.lower() or "no funciona" in mensaje.lower()


def test_carpeta_de_entrada_faltante_cuando_se_requiere() -> None:
    config = ConfiguracionOperador(db_url="sqlite:///:memory:", entrada=None)

    hallazgos = diagnosticar(config, requiere_entrada=True, requiere_red=False)

    assert _ok(hallazgos, "Carpeta a procesar") is False
    assert "--entrada" in _mensaje(hallazgos, "Carpeta a procesar") or "entrada" in _mensaje(
        hallazgos, "Carpeta a procesar"
    )


def test_carpeta_de_entrada_que_no_existe(tmp_path) -> None:
    config = ConfiguracionOperador(db_url="sqlite:///:memory:", entrada=tmp_path / "no-existe")

    hallazgos = diagnosticar(config, requiere_entrada=True, requiere_red=False)

    assert _ok(hallazgos, "Carpeta a procesar") is False
    assert "no existe" in _mensaje(hallazgos, "Carpeta a procesar").lower()


def test_carpeta_de_entrada_que_es_un_archivo_no_una_carpeta(tmp_path) -> None:
    archivo = tmp_path / "esto-es-un-archivo.txt"
    archivo.write_text("no es una carpeta", encoding="utf-8")
    config = ConfiguracionOperador(db_url="sqlite:///:memory:", entrada=archivo)

    hallazgos = diagnosticar(config, requiere_entrada=True, requiere_red=False)

    assert _ok(hallazgos, "Carpeta a procesar") is False
    assert "no es una carpeta" in _mensaje(hallazgos, "Carpeta a procesar").lower()


def test_carpeta_de_entrada_sin_permiso_de_lectura(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows no soporta bien `chmod` para simular ACL en un test portable
    -- se fuerza `os.access` para ejercitar la rama de "sin permisos" sin
    depender de la ACL real del sistema operativo."""
    carpeta = tmp_path / "sin-permiso"
    carpeta.mkdir()
    config = ConfiguracionOperador(db_url="sqlite:///:memory:", entrada=carpeta)

    monkeypatch.setattr("anonimizacion.diagnostico.os.access", lambda *_a, **_k: False)

    hallazgos = diagnosticar(config, requiere_entrada=True, requiere_red=False)

    assert _ok(hallazgos, "Carpeta a procesar") is False
    assert "permiso" in _mensaje(hallazgos, "Carpeta a procesar").lower()


# --- revisión adversarial, CRÍTICO 1: chequeo de corrida activa ------------


def test_corrida_activa_ninguna_es_ok(tmp_path) -> None:
    from anonimizacion.diagnostico import _diagnosticar_corrida_activa
    from anonimizacion.salida.modelos_orm import Base

    db_url = f"sqlite:///{tmp_path / 'db.sqlite3'}"
    engine = sa.create_engine(db_url)
    Base.metadata.create_all(engine)

    hallazgo = _diagnosticar_corrida_activa(db_url)

    assert hallazgo.ok is True


def test_corrida_activa_con_evidencia_reciente_pide_esperar(tmp_path) -> None:
    """Una corrida GENUINAMENTE en curso (evidencia reciente, <15 min) tiene
    que seguir bloqueando -- eso es correcto, no el bug. El mensaje sólo
    tiene que ser honesto: decir que hay que esperar cuando de verdad tiene
    sentido esperar."""
    from anonimizacion.diagnostico import _diagnosticar_corrida_activa
    from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
    from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
    from anonimizacion.salida.cuarentena import EscritorCuarentena
    from anonimizacion.salida.modelos_orm import Base

    db_url = f"sqlite:///{tmp_path / 'db.sqlite3'}"
    engine = sa.create_engine(db_url)
    Base.metadata.create_all(engine)
    carpeta = tmp_path / "en-curso"
    carpeta.mkdir()
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(engine), cuarentena=EscritorCuarentena(engine))
    lanzador.lanzar(carpeta)

    hallazgo = _diagnosticar_corrida_activa(db_url)

    assert hallazgo.ok is False
    assert "esper" in hallazgo.mensaje.lower()


def test_corrida_activa_abandonada_se_recupera_sola_y_reporta_ok(tmp_path) -> None:
    """CRÍTICO 1 (revisión adversarial): "agregá al diagnóstico un chequeo de
    corrida activa, con un mensaje que diga qué hacer -- no que repita una
    espera que no va a llegar". Una corrida SIN evidencia reciente (el
    proceso que la lanzó murió, la máquina se reinició) no se reporta como
    "esperar" -- se recupera sola, reutilizando la MISMA lógica que
    `servir_panel.py` ya usa en cada arranque
    (`lanzador_corrida.recuperar_corridas_abandonadas`), y el diagnóstico
    queda en OK: ya no hay nada que bloquee la próxima corrida."""
    from datetime import datetime, timedelta, timezone

    from anonimizacion.diagnostico import _diagnosticar_corrida_activa
    from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
    from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
    from anonimizacion.salida.cuarentena import EscritorCuarentena
    from anonimizacion.salida.modelos_orm import Base

    db_url = f"sqlite:///{tmp_path / 'db.sqlite3'}"
    engine = sa.create_engine(db_url)
    Base.metadata.create_all(engine)
    carpeta = tmp_path / "abandonada"
    carpeta.mkdir()
    repositorio = RepositorioCorridas(engine)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=EscritorCuarentena(engine))
    lanzador.lanzar(carpeta)

    veinte_minutos_despues = datetime.now(timezone.utc) + timedelta(minutes=20)
    hallazgo = _diagnosticar_corrida_activa(db_url, ahora=veinte_minutos_despues)

    assert hallazgo.ok is True
    assert repositorio.listar_corridas_no_terminales() == []


def test_carpeta_de_entrada_accesible_es_ok(tmp_path) -> None:
    carpeta = tmp_path / "pdfs"
    carpeta.mkdir()
    config = ConfiguracionOperador(db_url="sqlite:///:memory:", entrada=carpeta)

    hallazgos = diagnosticar(config, requiere_entrada=True, requiere_red=False)

    assert _ok(hallazgos, "Carpeta a procesar") is True


# --- contra Postgres real (docker-compose.yml, puerto 5433) -----------------


@pytest.fixture()
def _postgres_real_al_dia(monkeypatch: pytest.MonkeyPatch):
    """Base Postgres real, EFÍMERA y propia de este archivo -- NO la base
    compartida `anonimizacion` de puerto 5433. Migrada con `alembic upgrade
    head` PROGRAMÁTICO, mismo patrón que
    `tests/salida/test_migraciones.py::_url_postgres_scratch` y
    `tests/test_cli.py::_postgres_real_para_cli`.

    Antes este fixture corría directo contra la base COMPARTIDA: hacía
    `Base.metadata.drop_all` + `DROP TABLE alembic_version` para partir de
    cero (otros tests de la suite arman el esquema con `create_all`/
    `drop_all` sin pasar por Alembic, así que un `upgrade head` ahí chocaba
    con tablas ya existentes) y al final volvía a dejarla en `head` "para no
    romper otros tests/marks" -- esa misma frase ya delataba que el fixture
    sabía que estaba ensuciando un recurso ajeno. Entre el `drop_all` y el
    `upgrade head` había una ventana real sin tablas: cualquier otro test
    corriendo en paralelo contra esa base fallaba con `UndefinedTable`
    (causa confirmada de la falla intermitente de
    `tests/integracion/test_reintentar_no_duplica.py`). Con una base
    descartable propia, la ventana de borrado desaparece y el
    `upgrade head` final ya no hace falta -- nadie más la usa.
    `skip` si Postgres real no responde."""
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    motor_admin = sa.create_engine(
        _URL_POSTGRES_ADMIN, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    try:
        with motor_admin.connect() as conexion:
            conexion.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :nombre_base AND pid <> pg_backend_pid()"
                ),
                {"nombre_base": _NOMBRE_BASE_SCRATCH_DIAGNOSTICO},
            )
            conexion.execute(sa.text(f"DROP DATABASE IF EXISTS {_NOMBRE_BASE_SCRATCH_DIAGNOSTICO}"))
            conexion.execute(sa.text(f"CREATE DATABASE {_NOMBRE_BASE_SCRATCH_DIAGNOSTICO}"))
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexión es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_ADMIN}: {excepcion}")
        return

    url_scratch = _URL_POSTGRES_ADMIN.rsplit("/", 1)[0] + f"/{_NOMBRE_BASE_SCRATCH_DIAGNOSTICO}"
    try:
        cfg = Config(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", url_scratch)
        command.upgrade(cfg, "head")
        yield cfg, url_scratch
    finally:
        motor_admin.dispose()
        with sa.create_engine(
            _URL_POSTGRES_ADMIN, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
        ).connect() as conexion:
            conexion.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :nombre_base AND pid <> pg_backend_pid()"
                ),
                {"nombre_base": _NOMBRE_BASE_SCRATCH_DIAGNOSTICO},
            )
            conexion.execute(sa.text(f"DROP DATABASE IF EXISTS {_NOMBRE_BASE_SCRATCH_DIAGNOSTICO}"))


@pytest.mark.postgres
def test_migraciones_al_dia_contra_postgres_real(_postgres_real_al_dia) -> None:
    _cfg, url_scratch = _postgres_real_al_dia
    config = ConfiguracionOperador(db_url=url_scratch)

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Migraciones") is True


@pytest.mark.postgres
def test_migraciones_desactualizadas_contra_postgres_real(_postgres_real_al_dia) -> None:
    cfg, url_scratch = _postgres_real_al_dia
    script = ScriptDirectory.from_config(cfg)
    revisiones = list(script.walk_revisions())
    revision_anterior = revisiones[1].revision  # una atrás de head
    command.downgrade(cfg, revision_anterior)

    config = ConfiguracionOperador(db_url=url_scratch)
    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=False)

    assert _ok(hallazgos, "Migraciones") is False
    assert "alembic upgrade head" in _mensaje(hallazgos, "Migraciones")
