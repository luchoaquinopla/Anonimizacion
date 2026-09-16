"""Compuerta mecánica de la poda de prosa (Entrega 6, auditoria-y-poda).

design.md D6: compara el AST de cada `.py` modificado bajo `src/`, `tests/`,
`migrations/`, `scripts/` (`_CARPETAS_ALCANCE`) antes y después de la poda,
ignorando docstrings (los comentarios `#` ni siquiera llegan al AST -- el
tokenizador los descarta). Si el árbol normalizado cambió, la compuerta
falla: el diff tocó algo más que prosa. Un `.py` agregado, borrado o
renombrado en ese alcance también es una violación -- una poda no crea,
borra ni mueve archivos (`git diff --no-renames`, ver `_estado_archivos_python`).

Límite real, declarado a propósito: esto prueba que la poda NO tocó código
ejecutable. NO prueba que no se perdió conocimiento -- eso lo garantiza la
migración a Obsidian (Requisito 3 de la spec `prosa-de-codigo`), un paso
humano previo, no mecánico.

Ciclo de vida de la referencia (`_resolver_ref`): `COMPUERTA_AST_REF`
explícita e inexistente FALLA (se pidió a mano); sin ella, si falta la base
por defecto (`feat/auditoria-y-poda`) se SALTEA con el motivo y cómo activarla.
"""

from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

_RAIZ_REPO = Path(__file__).resolve().parents[2]
# La poda de prosa toca .py bajo estas 4 carpetas -- única constante de alcance.
# `tests/prosa` (la propia compuerta) se excluye: auditarse a sí misma no tiene sentido,
# y este mismo módulo es un archivo nuevo que PR6a agrega (no una poda).
_CARPETAS_ALCANCE = ("src", "tests", "migrations", "scripts", ":(exclude)tests/prosa")
_REF_POR_DEFECTO = "feat/auditoria-y-poda"


def _ejecutar_git(
    args: list[str], raiz_repo: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Wrapper único de `git` para toda la compuerta: sin `git` en el PATH, saltea con
    motivo claro en vez de dejar pasar un `FileNotFoundError` crudo."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=raiz_repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=check,
        )
    except FileNotFoundError as error:
        pytest.skip(f"'git' no está disponible en el PATH: {error}")


class RefCompuertaInvalida(Exception):
    """`COMPUERTA_AST_REF` fue definida a mano y no existe en este checkout."""


def _resolver_ref(
    ref_explicita: str | None = None, raiz_repo: Path = _RAIZ_REPO
) -> str:
    """Política de ciclo de vida: ref explícita inválida FALLA (alguien la pidió a
    mano); sin ref explícita, sin la base por defecto se SALTEA (no aplica todavía)."""
    if ref_explicita is None:
        ref_explicita = os.environ.get("COMPUERTA_AST_REF")
    if ref_explicita is not None:
        if not _ref_existe(ref_explicita, raiz_repo):
            raise RefCompuertaInvalida(
                f"COMPUERTA_AST_REF='{ref_explicita}' no existe en este checkout."
            )
        return ref_explicita
    if not _ref_existe(_REF_POR_DEFECTO, raiz_repo):
        pytest.skip(
            f"Referencia por defecto '{_REF_POR_DEFECTO}' no existe -- la compuerta AST "
            "sólo aplica durante una poda de prosa activa contra su rama base. Para "
            "forzarla, definí COMPUERTA_AST_REF=<rama base>."
        )
    return _REF_POR_DEFECTO


def _ref_existe(ref: str, raiz_repo: Path = _RAIZ_REPO) -> bool:
    resultado = _ejecutar_git(["rev-parse", "--verify", "--quiet", ref], raiz_repo, check=False)
    return resultado.returncode == 0


def _estado_archivos_python(ref: str, raiz_repo: Path = _RAIZ_REPO) -> list[tuple[str, str]]:
    """(estado, ruta) de cada .py bajo _CARPETAS_ALCANCE que difiere entre `ref` y el working
    tree. `--no-renames`: un `git mv` con --no-renames aparece como D (viejo) + A (nuevo),
    nunca como R -- así un renombre no puede colarse como 'sin cambios'."""
    resultado = _ejecutar_git(
        ["diff", "--name-status", "--no-renames", ref, "--", *_CARPETAS_ALCANCE], raiz_repo
    )
    salida: list[tuple[str, str]] = []
    for linea in resultado.stdout.splitlines():
        estado, _, ruta = linea.partition("\t")
        if ruta.endswith(".py"):
            salida.append((estado, ruta))
    return salida


def _contenido_en_ref(ref: str, ruta_relativa: str, raiz_repo: Path = _RAIZ_REPO) -> str:
    resultado = _ejecutar_git(["show", f"{ref}:{ruta_relativa}"], raiz_repo)
    return resultado.stdout


def _contenido_actual(ruta_relativa: str, raiz_repo: Path = _RAIZ_REPO) -> str:
    return (raiz_repo / ruta_relativa).read_text(encoding="utf-8")


def _es_docstring(nodo: ast.stmt) -> bool:
    return (
        isinstance(nodo, ast.Expr)
        and isinstance(nodo.value, ast.Constant)
        and isinstance(nodo.value.value, str)
    )


def _quitar_docstrings(arbol: ast.AST) -> ast.AST:
    """Retira el docstring inicial de módulo, clase y función, in-place."""
    contenedores = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, contenedores) and nodo.body and _es_docstring(nodo.body[0]):
            nodo.body.pop(0)
    return arbol


def normalizar(codigo_fuente: str) -> str:
    """AST del código sin docstrings, volcado ignorando line/col (números irrelevantes)."""
    arbol = ast.parse(codigo_fuente)
    arbol = _quitar_docstrings(arbol)
    return ast.dump(arbol, include_attributes=False)


@dataclass(frozen=True)
class ResultadoCompuerta:
    violaciones_estructurales: tuple[tuple[str, str], ...]  # (estado, ruta), estado != "M"
    fallos_ast: dict[str, tuple[str, str]]  # ruta -> (ast_antes, ast_despues), sólo estado "M"


def verificar_compuerta(ref: str, raiz_repo: Path = _RAIZ_REPO) -> ResultadoCompuerta:
    """Evalúa la compuerta completa: violaciones estructurales (archivos .py agregados,
    borrados o renombrados) y, sobre los modificados, si su AST sin docstrings cambió."""
    estados = _estado_archivos_python(ref, raiz_repo)
    violaciones = tuple((estado, ruta) for estado, ruta in estados if estado != "M")
    fallos: dict[str, tuple[str, str]] = {}
    for estado, ruta in estados:
        if estado != "M":
            continue
        antes = normalizar(_contenido_en_ref(ref, ruta, raiz_repo))
        despues = normalizar(_contenido_actual(ruta, raiz_repo))
        if antes != despues:
            fallos[ruta] = (antes, despues)
    return ResultadoCompuerta(violaciones, fallos)


@pytest.fixture(scope="module")
def ref_compuerta() -> str:
    try:
        return _resolver_ref()
    except RefCompuertaInvalida as error:
        pytest.fail(str(error))


@pytest.fixture(scope="module")
def resultado_compuerta(ref_compuerta: str) -> ResultadoCompuerta:
    return verificar_compuerta(ref_compuerta)


def test_poda_no_agrega_ni_borra_ni_renombra_archivos_python(
    resultado_compuerta: ResultadoCompuerta,
) -> None:
    assert not resultado_compuerta.violaciones_estructurales, (
        "Una poda de prosa no agrega, borra ni renombra archivos .py -- violaciones: "
        f"{resultado_compuerta.violaciones_estructurales}"
    )


def test_poda_no_cambia_el_ast_de_ningun_modulo_tocado(
    resultado_compuerta: ResultadoCompuerta,
) -> None:
    assert not resultado_compuerta.fallos_ast, (
        "El AST (sin docstrings) cambió en módulos que la poda de prosa no debía tocar: "
        f"{sorted(resultado_compuerta.fallos_ast)}"
    )


def _crear_repo_git(raiz: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=raiz, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.co", "-c", "user.name=t", "commit", "--allow-empty", "-q", "-m", "vacio"], cwd=raiz, check=True)


def _commit_todo(raiz: Path, mensaje: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=raiz, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.co", "-c", "user.name=t", "commit", "-q", "-m", mensaje], cwd=raiz, check=True)
    resultado = subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, capture_output=True, text=True, check=True)
    return resultado.stdout.strip()


def test_detecta_archivo_py_renombrado_como_violacion(tmp_path: Path) -> None:
    """RED (corrección 1): con --diff-filter=M, `git mv archivo.py otro.py` + editar
    código pasaba colado -- el archivo renombrado nunca aparecía como 'modificado', así
    que su AST nunca se comparaba contra nada."""
    raiz = tmp_path
    _crear_repo_git(raiz)
    (raiz / "src" / "anonimizacion").mkdir(parents=True)
    (raiz / "src" / "anonimizacion" / "modulo.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    base = _commit_todo(raiz, "base")

    subprocess.run(
        ["git", "mv", "src/anonimizacion/modulo.py", "src/anonimizacion/otro.py"], cwd=raiz, check=True
    )
    (raiz / "src" / "anonimizacion" / "otro.py").write_text("def f():\n    return 2\n", encoding="utf-8")

    resultado = verificar_compuerta(base, raiz_repo=raiz)
    rutas_violadas = {ruta for _, ruta in resultado.violaciones_estructurales}
    assert rutas_violadas & {"src/anonimizacion/modulo.py", "src/anonimizacion/otro.py"}, (
        "un renombre + edicion de un .py debe reportarse como violacion estructural, "
        f"no colarse como 'sin cambios' -- violaciones vistas: {resultado.violaciones_estructurales}"
    )


def test_alcance_incluye_tests_migrations_y_scripts(tmp_path: Path) -> None:
    """RED (corrección 2): hoy el alcance es sólo `src/anonimizacion` -- un cambio de
    código real en un .py de `tests/` (o `migrations/`, `scripts/`) no se detecta,
    aunque la poda real de comentarios también va a tocar esas carpetas."""
    raiz = tmp_path
    _crear_repo_git(raiz)
    (raiz / "tests").mkdir()
    (raiz / "tests" / "test_modulo.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    base = _commit_todo(raiz, "base")

    (raiz / "tests" / "test_modulo.py").write_text("def f():\n    return 2\n", encoding="utf-8")

    resultado = verificar_compuerta(base, raiz_repo=raiz)
    assert "tests/test_modulo.py" in resultado.fallos_ast, (
        "un cambio de codigo real en tests/ debe detectarse -- el alcance de la "
        f"compuerta no puede quedarse en src/anonimizacion. Resultado: {resultado}"
    )


def test_ref_explicita_inexistente_falla_en_vez_de_saltear() -> None:
    """RED (corrección 3): hoy, si `COMPUERTA_AST_REF` apunta a una ref que no existe, el
    fixture hace `pytest.skip` en silencio. Si alguien la definió a mano, está pidiendo la
    verificación -- una ref inválida debe fallar, no saltearse."""
    with pytest.raises(RefCompuertaInvalida):
        _resolver_ref(ref_explicita="esta-ref-no-existe-de-ninguna-forma-jamas-en-la-vida")


def test_sin_ref_explicita_se_saltea_si_no_existe_la_de_defecto(tmp_path: Path) -> None:
    """Sin COMPUERTA_AST_REF, y sin la rama base por defecto (repo nuevo/clon sin fetch),
    la compuerta se saltea explícitamente -- distinto del caso anterior."""
    raiz = tmp_path
    _crear_repo_git(raiz)
    with pytest.raises(pytest.skip.Exception):
        _resolver_ref(ref_explicita=None, raiz_repo=raiz)


def test_sin_git_en_el_path_se_saltea(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED (corrección 4): si `git` no está en el PATH, `subprocess.run` lanza
    `FileNotFoundError` crudo -- debe convertirse en un `pytest.skip` con motivo claro."""

    def _run_falso(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git no encontrado")

    monkeypatch.setattr(subprocess, "run", _run_falso)
    with pytest.raises(pytest.skip.Exception):
        _ejecutar_git(["rev-parse", "HEAD"], _RAIZ_REPO)


def test_normalizar_ignora_docstrings_pero_no_codigo() -> None:
    """Control unitario de la propia compuerta, sin depender de git ni de una referencia."""
    solo_docstring_distinto = (
        'def f(x):\n    """docstring viejo"""\n    return x + 1\n',
        'def f(x):\n    """docstring nuevo, mas corto"""\n    return x + 1\n',
    )
    assert normalizar(solo_docstring_distinto[0]) == normalizar(solo_docstring_distinto[1])

    codigo_distinto = (
        "def f(x):\n    return x + 1\n",
        "def f(x):\n    return x + 2\n",
    )
    assert normalizar(codigo_distinto[0]) != normalizar(codigo_distinto[1])
