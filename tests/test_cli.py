"""Tests de `anonimizacion.cli` -- punto de entrada único instalable
(`[project.scripts] anonimizacion`, `arranque-para-el-instituto`).

Reemplaza los dos scripts sueltos (`scripts/procesar_carpeta.py`,
`scripts/servir_panel.py`) por subcomandos de UN solo comando instalado.
Este es el camino REAL, no sólo objeto de tests: `pyproject.toml` registra
`anonimizacion = "anonimizacion.cli:main"` -- ver `test_pyproject_registra_el_punto_de_entrada_unico`.

Los scripts viejos siguen existiendo sin tocarlos (hay un PR abierto,
#40, que también los toca -- ver el docstring de `anonimizacion.cli`):
este módulo los invoca por ruta, exactamente como ya hacían
`tests/scripts/test_procesar_carpeta.py`/`test_servir_panel.py`, y traduce
la configuración resuelta a los mismos argumentos de línea de comandos que
esos scripts ya entienden.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from anonimizacion import cli
from anonimizacion.diagnostico import Hallazgo
from anonimizacion.pseudonimizacion.almacen_pepper import obtener_pepper
from anonimizacion.web.secreto_panel import obtener_secreto_panel


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


def test_procesar_no_delega_al_script_si_el_diagnostico_falla(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _con_error("Carpeta a procesar: no existe."))
    llamado = []
    monkeypatch.setattr(cli, "_cargar_script", lambda nombre: llamado.append(nombre) or None)

    codigo = cli.main(["procesar", "--entrada", str(tmp_path)])

    assert codigo == 1
    assert llamado == [], "no debe invocar el script real si el diagnóstico encontró un problema"


def test_procesar_arma_el_argv_correcto_y_delega_al_script_real(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())

    argv_capturado: list[str] = []

    class _ScriptFalso:
        @staticmethod
        def main():
            import sys

            argv_capturado.extend(sys.argv)
            return 0

    monkeypatch.setattr(cli, "_cargar_script", lambda nombre: _ScriptFalso())

    entrada = tmp_path / "pdfs"
    entrada.mkdir()
    codigo = cli.main(["procesar", "--entrada", str(entrada), "--db-url", "postgresql+psycopg://x/y", "--procesos", "2"])

    assert codigo == 0
    assert "--entrada" in argv_capturado
    assert str(entrada) in argv_capturado
    assert "--db-url" in argv_capturado
    assert "postgresql+psycopg://x/y" in argv_capturado
    assert "--procesos" in argv_capturado
    assert "2" in argv_capturado


def test_servir_agrega_escuchar_red_solo_si_se_pide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())

    argv_capturado: list[str] = []

    class _ScriptFalso:
        @staticmethod
        def main():
            import sys

            argv_capturado.extend(sys.argv)
            return 0

    monkeypatch.setattr(cli, "_cargar_script", lambda nombre: _ScriptFalso())

    codigo = cli.main(["servir"])

    assert codigo == 0
    assert "--escuchar-red" not in argv_capturado


def test_servir_con_bandera_agrega_escuchar_red(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: _todo_ok())

    argv_capturado: list[str] = []

    class _ScriptFalso:
        @staticmethod
        def main():
            import sys

            argv_capturado.extend(sys.argv)
            return 0

    monkeypatch.setattr(cli, "_cargar_script", lambda nombre: _ScriptFalso())

    codigo = cli.main(["servir", "--escuchar-red"])

    assert codigo == 0
    assert "--escuchar-red" in argv_capturado


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

    argv_capturado: list[str] = []

    class _ScriptFalso:
        @staticmethod
        def main():
            import sys

            argv_capturado.extend(sys.argv)
            return 0

    monkeypatch.setattr(cli, "_cargar_script", lambda nombre: _ScriptFalso())

    codigo = cli.main(["procesar", "--config", str(config_toml)])

    assert codigo == 0
    assert str(entrada) in argv_capturado
    assert "postgresql+psycopg://config/db" in argv_capturado
    assert "5" in argv_capturado


def test_pyproject_registra_el_punto_de_entrada_unico() -> None:
    raiz = Path(__file__).resolve().parents[1]
    datos = tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))

    assert datos["project"]["scripts"]["anonimizacion"] == "anonimizacion.cli:main"
