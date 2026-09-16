"""Tests de `anonimizacion.cli` -- punto de entrada único instalable
(`[project.scripts] anonimizacion`, `arranque-para-el-instituto`).

Reemplaza los dos scripts sueltos que existían antes de `auditoria-y-poda`
E4 (`scripts/procesar_carpeta.py`, `scripts/servir_panel.py`) por
subcomandos de UN solo comando instalado. Este es el camino REAL, no sólo
objeto de tests: `pyproject.toml` registra
`anonimizacion = "anonimizacion.cli:main"` -- ver `test_pyproject_registra_el_punto_de_entrada_unico`.

Desde E4, `cli.py` ya no carga nada por ruta ni re-parsea `sys.argv`: llama
`anonimizacion.comandos.procesar.ejecutar(...)`/
`anonimizacion.comandos.servir.servir(...)` con argumentos con nombre. Los
tests de este módulo mockean esas funciones de comando (no un cargador) --
ver `cli.comandos_procesar`/`cli.comandos_servir`.
"""

from __future__ import annotations

import socket
import tomllib
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from anonimizacion import cli
from anonimizacion.diagnostico import Hallazgo
from anonimizacion.pseudonimizacion.almacen_pepper import obtener_pepper
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.salida.modelos_orm import CorridaOrm, Estudio
from anonimizacion.trabajadores.despacho_paralelo import tope_duro_concurrencia
from anonimizacion.web.secreto_panel import obtener_secreto_panel

from .comandos.test_procesar import _CONNECT_REAL, _grupo_completo

_URL_POSTGRES_ADMIN = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
_NOMBRE_BASE_SCRATCH_CLI = "cli_scratch_test"
_RAIZ_REPO = Path(__file__).resolve().parent.parent


def _config_alembic(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_RAIZ_REPO / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _terminar_conexiones_y_dropear(conexion: sa.Connection, nombre_base: str) -> None:
    """`DROP DATABASE` falla con `ObjectInUse` si queda alguna sesión abierta.
    Los procesos hijos de `--procesos 2` (`ProcessPoolExecutor`) abren su
    propio pool de conexiones contra la base efímera; el final de esos
    procesos no siempre cierra el socket antes de que este fixture intente
    borrar la base, así que se terminan explícitamente las conexiones
    restantes de esa base antes del `DROP`."""
    conexion.execute(
        sa.text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :nombre_base AND pid <> pg_backend_pid()"
        ),
        {"nombre_base": nombre_base},
    )
    conexion.execute(sa.text(f"DROP DATABASE IF EXISTS {nombre_base}"))


@pytest.fixture(autouse=True)
def _limpiar_caches_de_secretos(monkeypatch: pytest.MonkeyPatch):
    obtener_pepper.cache_clear()
    obtener_secreto_panel.cache_clear()
    monkeypatch.delenv("ANONIMIZACION_PEPPER", raising=False)
    monkeypatch.delenv("ANONIMIZACION_PEPPER_ARCHIVO", raising=False)
    monkeypatch.delenv("ANONIMIZACION_PANEL_SECRETO", raising=False)
    monkeypatch.delenv("ANONIMIZACION_PANEL_SECRETO_ARCHIVO", raising=False)
    monkeypatch.delenv("ANONIMIZACION_CONFIG", raising=False)
    yield
    obtener_pepper.cache_clear()
    obtener_secreto_panel.cache_clear()


def _todo_ok() -> list[Hallazgo]:
    return [Hallazgo(True, "Pepper: configurado.")]


def _con_error(mensaje: str = "Base de datos: no se pudo conectar.") -> list[Hallazgo]:
    return [Hallazgo(True, "Pepper: configurado."), Hallazgo(False, mensaje)]


def test_diagnosticar_todo_en_orden_devuelve_cero(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())

    codigo = cli.main(["diagnosticar"])

    assert codigo == 0
    assert "Todo en orden" in capsys.readouterr().err


def test_diagnosticar_con_hallazgo_en_error_devuelve_uno(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _con_error())

    codigo = cli.main(["diagnosticar"])

    assert codigo == 1
    salida = capsys.readouterr().err
    assert "no se pudo conectar" in salida


def test_diagnosticar_con_configuracion_invalida_da_mensaje_claro_sin_traceback(tmp_path, capsys) -> None:
    ruta = tmp_path / "anonimizacion.toml"
    ruta.write_text("puertos = 9000\n", encoding="utf-8")  # error de tipeo real

    codigo = cli.main(["diagnosticar", "--config", str(ruta)])

    assert codigo == 1
    salida = capsys.readouterr().err
    assert "puertos" in salida
    assert "Traceback" not in salida


def _permitir_composicion_de_procesar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Composición real de `_comando_procesar` antes de llegar a `ejecutar()`
    -- pepper/motor/engine -- mockeada para que los tests de este archivo no
    toquen spaCy/Postgres reales."""
    monkeypatch.setattr(cli, "obtener_pepper", lambda: b"pepper-test-cli-nunca-real")
    monkeypatch.setattr(cli, "MotorPii", lambda: object())
    monkeypatch.setattr(cli, "construir_engine_postgres", lambda url: sa.create_engine("sqlite:///:memory:"))


def test_procesar_no_delega_al_comando_si_el_diagnostico_falla(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _con_error("Carpeta a procesar: no existe."))
    llamado = []
    monkeypatch.setattr(cli.comandos_procesar, "ejecutar", lambda **kwargs: llamado.append(kwargs) or 0)

    codigo = cli.main(["procesar", "--entrada", str(tmp_path)])

    assert codigo == 1
    assert llamado == [], "no debe invocar ejecutar() si el diagnóstico encontró un problema"


def test_procesar_resuelve_los_argumentos_correctos_y_delega_a_ejecutar(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())
    _permitir_composicion_de_procesar(monkeypatch)

    capturado: dict[str, object] = {}
    monkeypatch.setattr(cli.comandos_procesar, "ejecutar", lambda **kwargs: capturado.update(kwargs) or 0)

    entrada = tmp_path / "pdfs"
    entrada.mkdir()
    codigo = cli.main(["procesar", "--entrada", str(entrada), "--db-url", "postgresql+psycopg://x/y", "--procesos", "2"])

    assert codigo == 0
    assert capturado["entrada"] == entrada
    assert capturado["db_url"] == "postgresql+psycopg://x/y"
    assert capturado["procesos"] == 2


def test_servir_agrega_escuchar_red_solo_si_se_pide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())

    capturado: dict[str, object] = {}
    monkeypatch.setattr(cli.comandos_servir, "servir", lambda **kwargs: capturado.update(kwargs) or 0)

    codigo = cli.main(["servir"])

    assert codigo == 0
    assert capturado["escuchar_red"] is False


def test_servir_con_bandera_agrega_escuchar_red(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())

    capturado: dict[str, object] = {}
    monkeypatch.setattr(cli.comandos_servir, "servir", lambda **kwargs: capturado.update(kwargs) or 0)

    codigo = cli.main(["servir", "--escuchar-red"])

    assert codigo == 0
    assert capturado["escuchar_red"] is True


def test_servir_pide_el_secreto_del_panel_cuando_se_pide_escuchar_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin `--escuchar-red`, `diagnosticar` no exige el secreto del panel
    (mismo criterio que hoy tolera `servir_panel.py` sólo en 127.0.0.1) --
    con la bandera, sí. Este test ejercita `diagnosticar` DE VERDAD (no lo
    mockea) para confirmar que `cli.py` le pasa `requiere_red` correctamente."""
    llamado_con: dict = {}
    original = cli.diagnosticar

    def _espia(config, *, requiere_entrada, requiere_red):
        llamado_con["requiere_red"] = requiere_red
        return original(config, requiere_entrada=requiere_entrada, requiere_red=requiere_red)

    monkeypatch.setattr(cli, "diagnosticar", _espia)

    cli.main(["servir", "--escuchar-red"])

    assert llamado_con["requiere_red"] is True


def test_procesos_rechaza_valores_por_encima_del_tope_duro_en_procesar_y_servir() -> None:
    """Movido desde `tests/comandos/test_servir.py` (E4, design.md D3):
    `--procesos` se valida UNA sola vez, en el `argparse` de `cli.py` --
    antes estaba duplicado en cada script suelto."""
    tope = tope_duro_concurrencia()
    parser = cli._construir_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["procesar", "--entrada", "carpeta", "--procesos", str(tope + 1)])
    with pytest.raises(SystemExit):
        parser.parse_args(["servir", "--procesos", str(tope + 1)])


def test_servir_escuchar_red_es_false_por_defecto() -> None:
    """Movido desde `tests/comandos/test_servir.py` (E4): el default vive
    ahora en el `argparse` de `cli.py`."""
    parser = cli._construir_parser()

    args = parser.parse_args(["servir"])

    assert args.escuchar_red is False


def test_procesar_usa_construir_engine_postgres_no_create_engine_pelado(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Movido desde `tests/comandos/test_procesar.py` (E4): la composición
    del `Engine` -- `construir_engine_postgres`, no `sa.create_engine`
    pelado -- vive ahora en `cli.py::_comando_procesar`, no en `ejecutar()`
    (que ya recibe el `Engine` inyectado)."""
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())
    monkeypatch.setattr(cli, "obtener_pepper", lambda: b"pepper-wiring-pool-nunca-real")
    monkeypatch.setattr(cli, "MotorPii", lambda: object())
    monkeypatch.setattr(cli.comandos_procesar, "ejecutar", lambda **kwargs: 0)

    llamadas: list[str] = []

    def _engine_espia(url: str) -> sa.Engine:
        llamadas.append(url)
        return sa.create_engine("sqlite:///:memory:")

    monkeypatch.setattr(cli, "construir_engine_postgres", _engine_espia)

    codigo = cli.main(["procesar", "--entrada", str(tmp_path)])

    assert codigo == 0
    from anonimizacion.configuracion import ConfiguracionOperador

    assert llamadas == [ConfiguracionOperador().db_url]


def test_procesar_usa_los_valores_del_archivo_de_configuracion_si_no_hay_bandera(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    entrada = tmp_path / "pdfs-del-instituto"
    entrada.mkdir()
    config_toml = tmp_path / "anonimizacion.toml"
    config_toml.write_text(
        f'entrada = "{entrada.as_posix()}"\ndb_url = "postgresql+psycopg://config/db"\nprocesos = 5\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())
    _permitir_composicion_de_procesar(monkeypatch)

    capturado: dict[str, object] = {}
    monkeypatch.setattr(cli.comandos_procesar, "ejecutar", lambda **kwargs: capturado.update(kwargs) or 0)

    codigo = cli.main(["procesar", "--config", str(config_toml)])

    assert codigo == 0
    assert capturado["entrada"] == entrada
    assert capturado["db_url"] == "postgresql+psycopg://config/db"
    assert capturado["procesos"] == 5


# --- revisión adversarial, MAYOR 5: el camino de mayor riesgo no tenía test


@pytest.fixture()
def _postgres_real_para_cli(monkeypatch: pytest.MonkeyPatch):
    """Base Postgres real, EFÍMERA y propia de este test -- NO la base
    compartida `anonimizacion` de puerto 5433. Migrada con `alembic upgrade
    head` PROGRAMÁTICO, mismo patrón que
    `tests/salida/test_migraciones.py::_url_postgres_scratch`.

    Antes este fixture hacía `Base.metadata.drop_all`/`create_all` sobre la
    base COMPARTIDA sin tocar `alembic_version`: `cli.main` -> `diagnosticar()`
    -> `_diagnosticar_migraciones` (`diagnostico.py`) compara los heads del
    código (`ScriptDirectory.get_heads()`) contra `alembic_version` de esa
    base real -- un desalineamiento ahí (p. ej. tras agregar una migración
    nueva en esta rama) hacía que `procesar` fallara el diagnóstico a menos
    que alguien corriera `alembic upgrade head` A MANO contra la base
    compartida antes de la corrida, y de paso la dejaba mutada para
    cualquier otro test/desarrollador que la usara en paralelo. Ahora el
    test aplica las migraciones él mismo sobre una base descartable propia,
    sin depender de estado externo. `skip` si Postgres real no responde."""
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    motor_admin = sa.create_engine(
        _URL_POSTGRES_ADMIN, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    try:
        with motor_admin.connect() as conexion:
            _terminar_conexiones_y_dropear(conexion, _NOMBRE_BASE_SCRATCH_CLI)
            conexion.execute(sa.text(f"CREATE DATABASE {_NOMBRE_BASE_SCRATCH_CLI}"))
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexión es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_ADMIN}: {excepcion}")
        return

    url_scratch = _URL_POSTGRES_ADMIN.rsplit("/", 1)[0] + f"/{_NOMBRE_BASE_SCRATCH_CLI}"
    try:
        command.upgrade(_config_alembic(url_scratch), "head")
        engine = construir_engine_postgres(url_scratch)
        yield engine, url_scratch
        engine.dispose()
    finally:
        motor_admin.dispose()
        with sa.create_engine(
            _URL_POSTGRES_ADMIN, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
        ).connect() as conexion:
            _terminar_conexiones_y_dropear(conexion, _NOMBRE_BASE_SCRATCH_CLI)


@pytest.mark.postgres
def test_procesar_delega_de_punta_a_punta_al_script_real_con_procesos_reales(
    tmp_path, monkeypatch: pytest.MonkeyPatch, _postgres_real_para_cli
) -> None:
    """MAYOR 5 (revisión adversarial): todos los demás tests de `procesar`/
    `servir` en este archivo mockean `_cargar_script` con un `_ScriptFalso`
    -- ninguno ejercitaba el script REAL ni `ProcessPoolExecutor` por el
    camino nuevo (`cli.py` -> carga por ruta -> `scripts/procesar_carpeta.py`
    -> `despacho_paralelo`). Este es el único test de este archivo que NO
    mockea `_cargar_script`: carga el script de verdad y despacha con
    `--procesos 2` contra Postgres real -- si la traducción de argv de
    `cli.py` alguna vez se rompe (un nombre de bandera cambiado, un tipo mal
    convertido), este test lo detecta antes que un operador con 5 TB."""
    monkeypatch.setenv("ANONIMIZACION_PEPPER", "pepper-test-cli-real-mayor5-nunca-real")
    engine, url_scratch = _postgres_real_para_cli

    carpeta_1 = tmp_path / "paciente-1"
    carpeta_2 = tmp_path / "paciente-2"
    carpeta_1.mkdir()
    carpeta_2.mkdir()
    _grupo_completo(carpeta_1, "cli-real-1", dni="20555888", nombre="Ana Cli Real Uno")
    _grupo_completo(
        carpeta_2, "cli-real-2", dni="20666999", nombre="Beatriz Cli Real Dos",
        fecha_nac_lab="10/10/1985", fecha_nac_ecg="10-OCT-1985",
    )

    codigo = cli.main(
        ["procesar", "--entrada", str(tmp_path), "--db-url", url_scratch, "--procesos", "2"]
    )

    assert codigo == 0
    with Session(engine) as sesion:
        corridas = sesion.scalars(sa.select(CorridaOrm)).all()
        estudios = sesion.scalars(sa.select(Estudio)).all()
    assert len(corridas) == 1
    assert corridas[0].estado == "completada"
    assert len(estudios) == 6, "particion exhaustiva: los dos pacientes se publican, cada uno en su proceso"


def test_esqueleto_genera_fixture_sin_pii_y_reporta_tipo_detectado(tmp_path, capsys) -> None:
    """Tarea "herramienta de esqueleto de formato": el subcomando extrae por
    el mismo camino que producción (`extraccion/texto_pymupdf.py`), enmascara
    y reporta el tipo detectado + puntaje de la firma, sin requerir ninguna
    configuración de base de datos (a diferencia de `procesar`/`servir`)."""
    from tests.fixtures.pdf_sintetico import crear_pdf_con_texto

    pdf = crear_pdf_con_texto(
        tmp_path / "muestra.pdf",
        paginas=["HEMATOLOGIA\nApellido y Nombre: Fernandez Marta\nDNI: 28999111\n"],
    )
    salida = tmp_path / "esqueleto.txt"

    codigo = cli.main(["esqueleto", str(pdf), "--salida", str(salida)])

    assert codigo == 0
    contenido = salida.read_text(encoding="utf-8")
    assert "Fernandez Marta" not in contenido
    assert "28999111" not in contenido
    assert "HEMATOLOGIA" in contenido
    assert "Apellido y Nombre:" in contenido
    salida_stderr = capsys.readouterr().err
    assert "laboratorio" in salida_stderr


def test_esqueleto_sin_salida_imprime_a_stdout(tmp_path, capsys) -> None:
    from tests.fixtures.pdf_sintetico import crear_pdf_con_texto

    pdf = crear_pdf_con_texto(tmp_path / "muestra.pdf", paginas=["HEMATOLOGIA\nDNI: 28999111\n"])

    codigo = cli.main(["esqueleto", str(pdf)])

    assert codigo == 0
    salida_stdout = capsys.readouterr().out
    assert "28999111" not in salida_stdout
    assert "HEMATOLOGIA" in salida_stdout


def test_esqueleto_con_pdf_ilegible_informa_error_sin_ruta_cruda(tmp_path, capsys) -> None:
    pdf_corrupto = tmp_path / "corrupto.pdf"
    pdf_corrupto.write_bytes(b"esto no es un pdf valido")

    codigo = cli.main(["esqueleto", str(pdf_corrupto)])

    assert codigo == 1
    salida_stderr = capsys.readouterr().err
    assert "pdf_ilegible" in salida_stderr


def test_esqueleto_modo_parseable_genera_valores_sinteticos_en_vez_de_enmascarar(tmp_path, capsys) -> None:
    """Tarea "fixture parseable de esqueletos reales": `--modo parseable` usa
    la misma allowlist estructural pero sustituye contenido por valores
    SINTÉTICOS plausibles en vez de tapado por forma (`X`/`0`) -- a
    diferencia del modo default, no reporta puntaje de firma (ver
    `FixtureParseable`, que no lo modela)."""
    from tests.fixtures.pdf_sintetico import crear_pdf_con_texto

    pdf = crear_pdf_con_texto(
        tmp_path / "muestra.pdf",
        paginas=["HEMATOLOGIA\nApellido y Nombre: Fernandez Marta\nDNI: 28999111\n"],
    )
    salida = tmp_path / "fixture.txt"

    codigo = cli.main(["esqueleto", str(pdf), "--modo", "parseable", "--salida", str(salida)])

    assert codigo == 0
    contenido = salida.read_text(encoding="utf-8")
    assert "Fernandez Marta" not in contenido
    assert "28999111" not in contenido
    assert "X" * 9 not in contenido  # no es el modo enmascarado
    assert "HEMATOLOGIA" in contenido
    assert "Apellido y Nombre:" in contenido
    assert "SINTETICOS" in contenido
    salida_stderr = capsys.readouterr().err
    assert salida_stderr.strip().endswith("Tipo detectado: laboratorio.")


def test_exportar_delega_a_exportar_dataset_con_la_url_y_pagina_resueltas(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from anonimizacion.salida.exportacion import ResumenExportacion

    llamado_con: dict = {}

    def _falso_exportar_dataset(engine, salida, *, tamano_pagina):
        llamado_con["salida"] = salida
        llamado_con["tamano_pagina"] = tamano_pagina
        return ResumenExportacion(episodios=1, ecg=1, laboratorio=1, eco=1)

    monkeypatch.setattr(cli, "exportar_dataset", _falso_exportar_dataset)

    salida = tmp_path / "dataset"
    codigo = cli.main(
        ["exportar", "--db-url", "sqlite:///:memory:", "--salida", str(salida), "--tamano-pagina", "128"]
    )

    assert codigo == 0
    assert llamado_con["salida"] == salida
    assert llamado_con["tamano_pagina"] == 128


def test_exportar_produce_parquet_y_manifiesto_sin_mutar_la_base_sqlite(tmp_path, capsys) -> None:
    """Extremo real (sin mockear `exportar_dataset`): contra una base SQLite
    de archivo (no Postgres, pero ejercita `construir_engine_postgres` +
    `exportar_dataset` de punta a punta) -- confirma que el subcomando
    produce los 4 Parquet + manifiesto y que ninguna fila cambia como efecto
    de exportar."""
    from datetime import date

    import sqlalchemy as sa

    from anonimizacion.salida.modelos_orm import Base, Episodio, Estudio

    ruta_db = tmp_path / "exportar_cli.db"
    url = f"sqlite:///{ruta_db}"
    motor = sa.create_engine(url)
    Base.metadata.create_all(motor)
    with sa.orm.Session(motor) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio="ep-cli-1", id_paciente="pid-cli-1", fecha_ancla=date(2024, 3, 1)))
        sesion.add(
            Estudio(
                id_episodio="ep-cli-1",
                tipo_documento="laboratorio",
                fecha_estudio=date(2024, 3, 1),
                precision_hora="ausente",
                completo=False,
                campos_no_extraidos=["laboratorio.resultado"],
            )
        )
    motor.dispose()

    with sa.orm.Session(sa.create_engine(url)) as sesion:
        conteo_antes = sesion.scalar(sa.select(sa.func.count()).select_from(Estudio))

    salida = tmp_path / "dataset"
    codigo = cli.main(["exportar", "--db-url", url, "--salida", str(salida)])

    assert codigo == 0
    assert (salida / "episodios.parquet").exists()
    assert (salida / "manifiesto.json").exists()
    assert "Exportación completa" in capsys.readouterr().err

    with sa.orm.Session(sa.create_engine(url)) as sesion:
        conteo_despues = sesion.scalar(sa.select(sa.func.count()).select_from(Estudio))
    assert conteo_antes == conteo_despues == 1


def test_pyproject_registra_el_punto_de_entrada_unico() -> None:
    raiz = Path(__file__).resolve().parents[1]
    datos = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))

    assert datos["project"]["scripts"]["anonimizacion"] == "anonimizacion.cli:main"
