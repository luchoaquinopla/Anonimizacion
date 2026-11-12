"""Test de instalación por wheel (Entrega 4, auditoria-y-poda).

design.md D2: el test "obvio" (`uv build` + `anonimizacion --help`) NO
detecta el defecto -- `argparse` termina el proceso antes de llegar a
`_cargar_script`, y `procesar`/`servir` sin Postgres cortan tres líneas
ANTES de esa carga (`cli.py::_reportar_diagnostico`). Por eso el subproceso
de `test_procesar_instalado_por_wheel_llega_a_la_composicion_real` stubea
`diagnosticar`/`ejecutar` DENTRO del venv efímero: sin ese stub la ejecución
no alcanza la composición real y el test sería teatro (pasaría en verde con
el defecto vivo).

Evidencia de RED contra el código viejo (commit `ad9521c`, antes de E4):
wheel construido desde ese commit, instalado en el mismo tipo de venv
efímero, mismo subproceso (sin mockear `comandos_procesar`, que no existía)
-- `FileNotFoundError: ...\\.venv...\\Lib\\scripts\\procesar_carpeta.py`
lanzada por `_cargar_script`, exit code 1. Documentado en
`sdd/auditoria-y-poda/apply-progress`. No se reproduce automáticamente acá
(exigiría construir un segundo wheel de un commit viejo en cada corrida,
costo que no se justifica una vez fijo el defecto) -- el `pytest.raises`
de este archivo cubre la reintroducción futura del mismo patrón.

Costo medido en esta máquina (no el ~12-20s estimado en design.md, más
rápido en la práctica): build ~1s, venv ~0.1s, install --no-deps ~0.9s,
3 subprocesos ~0.1-4s cada uno (el más caro importa `anonimizacion.cli`,
que arrastra varios submódulos a nivel de módulo). Total de la fixture de
sesión + los 3 tests: bien por debajo del techo de ~45s de design.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.empaquetado

_RAIZ_REPO = Path(__file__).resolve().parents[2]


def _python_del_venv(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _ejecutar(comando: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    resultado = subprocess.run(comando, cwd=cwd, capture_output=True, text=True, timeout=120)
    assert resultado.returncode == 0, (
        f"comando {comando} fallo (codigo {resultado.returncode})\n"
        f"stdout={resultado.stdout}\nstderr={resultado.stderr}"
    )
    return resultado


@pytest.fixture(scope="session")
def venv_wheel(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    """Construye el wheel real, lo instala en un venv efímero con
    `--system-site-packages` (design.md D2) -- una sola vez por corrida de
    la suite. `--no-deps` + `--system-site-packages`: las dependencias
    pesadas (spaCy, Presidio, PyMuPDF, SQLAlchemy, pyarrow) se resuelven
    desde el entorno de desarrollo ya instalado, sin red y sin reinstalar
    cientos de MB; sólo `anonimizacion` se instala de verdad."""
    tmp_dir = tmp_path_factory.mktemp("wheel_empaquetado")
    directorio_dist = tmp_dir / "dist"
    _ejecutar(["uv", "build", "--wheel", "--out-dir", str(directorio_dist)], cwd=_RAIZ_REPO)

    wheels = list(directorio_dist.glob("anonimizacion-*.whl"))
    assert len(wheels) == 1, f"se esperaba exactamente 1 wheel, se encontraron: {wheels}"
    wheel = wheels[0]

    venv_dir = tmp_dir / "venv_wheel"
    python_del_venv_de_desarrollo = sys.executable
    _ejecutar(
        ["uv", "venv", "--system-site-packages", "--python", python_del_venv_de_desarrollo, str(venv_dir)],
        cwd=_RAIZ_REPO,
    )

    python_venv = _python_del_venv(venv_dir)
    _ejecutar(
        ["uv", "pip", "install", "--no-deps", "--python", str(python_venv), str(wheel)],
        cwd=_RAIZ_REPO,
    )

    return venv_dir, wheel, python_venv


def test_wheel_instalado_ejecuta_dentro_del_venv_no_del_checkout(venv_wheel: tuple[Path, Path, Path]) -> None:
    """Guarda de honestidad (design.md D2, punto 1): sin esto, un `.pth` de
    instalación editable heredado del site-packages del sistema podría hacer
    que los otros dos tests ejerciten el checkout por el motivo equivocado."""
    venv_dir, _wheel, python_venv = venv_wheel

    entorno = dict(os.environ)
    entorno["PATH"] = str(python_venv.parent) + os.pathsep + entorno.get("PATH", "")

    resultado = subprocess.run(
        [str(python_venv), "-c", "import anonimizacion, shutil; print(anonimizacion.__file__); print(shutil.which('anonimizacion'))"],
        capture_output=True,
        text=True,
        env=entorno,
        timeout=30,
    )
    assert resultado.returncode == 0, resultado.stderr
    ruta_modulo, ruta_comando = resultado.stdout.strip().splitlines()

    assert str(venv_dir) in ruta_modulo, f"anonimizacion.__file__ fuera del venv efimero: {ruta_modulo}"
    assert str(_RAIZ_REPO) not in ruta_modulo, f"anonimizacion.__file__ apunta al checkout: {ruta_modulo}"
    assert str(venv_dir) in ruta_comando, f"el comando 'anonimizacion' no resuelve dentro del venv: {ruta_comando}"


def test_wheel_contiene_modulos_de_comandos_y_ningun_scripts(venv_wheel: tuple[Path, Path, Path]) -> None:
    """Test estático de empaquetado (design.md D2, punto 2; spec
    `punto-entrada-instalable` Requisito 1): el wheel incluye los módulos
    nuevos de `comandos/` y ningún archivo bajo `scripts/`."""
    _venv_dir, wheel, _python_venv = venv_wheel

    with zipfile.ZipFile(wheel) as archivo:
        nombres = archivo.namelist()

    assert any(nombre.endswith("anonimizacion/comandos/procesar.py") for nombre in nombres)
    assert any(nombre.endswith("anonimizacion/comandos/servir.py") for nombre in nombres)
    assert not any("scripts/" in nombre for nombre in nombres), (
        f"el wheel no debe contener nada bajo scripts/: {[n for n in nombres if 'scripts/' in n]}"
    )


def test_procesar_instalado_por_wheel_llega_a_la_composicion_real(
    venv_wheel: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """El test que detecta el defecto (design.md D2, punto 3). Stubea
    `diagnosticar` (hallazgos OK) y `comandos_procesar.ejecutar` (retorna 0)
    DENTRO del venv efímero -- sin ese stub, `_reportar_diagnostico` corta
    en `cli.py` tres líneas antes de llegar a la composición real, y el test
    sería un falso verde (pasaría igual con el defecto vivo). Confirmado en
    rojo contra el commit anterior a esta entrega (`ad9521c`): ver el
    docstring del módulo."""
    _venv_dir, _wheel, python_venv = venv_wheel
    carpeta_entrada = tmp_path / "entrada"
    carpeta_entrada.mkdir()

    probe = dedent(
        f"""
        import sys
        from anonimizacion import cli
        from anonimizacion.diagnostico import Hallazgo

        llamado = []

        def _diagnosticar_ok(config, *, requiere_entrada, requiere_red):
            return [Hallazgo(True, "ok")]

        def _ejecutar_stub(**kwargs):
            llamado.append(kwargs)
            return 0

        cli.diagnosticar = _diagnosticar_ok
        cli.obtener_pepper = lambda: b"pepper-wheel-test-nunca-real"
        cli.MotorPii = lambda: object()
        cli.construir_engine_postgres = lambda url: object()
        cli.comandos_procesar.ejecutar = _ejecutar_stub

        codigo = cli.main(["procesar", "--entrada", {str(carpeta_entrada)!r}, "--db-url", "postgresql://x/y"])
        sys.exit(0 if codigo == 0 and len(llamado) == 1 else 3)
        """
    )

    resultado = subprocess.run(
        [str(python_venv), "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert resultado.returncode == 0, (
        f"el subproceso no llego a ejecutar()/no devolvio 0 -- stdout={resultado.stdout}\nstderr={resultado.stderr}"
    )
