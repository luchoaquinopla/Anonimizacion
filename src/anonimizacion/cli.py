"""Punto de entrada único instalable (`arranque-para-el-instituto`).

Antes de este módulo, operar el pipeline exigía clonar el repositorio y
lanzar DOS scripts sueltos (`scripts/procesar_carpeta.py`,
`scripts/servir_panel.py`), cada uno con su propio `argparse` y su propia URL
de base por defecto. Este módulo es el composition root real: un único
comando instalado (`[project.scripts]`, ver `pyproject.toml`) con
subcomandos --

    anonimizacion diagnosticar   # ¿está todo listo para operar?
    anonimizacion procesar --entrada <carpeta>
    anonimizacion servir

Fuera de alcance deliberado de este cambio (ver la respuesta completa en
`sdd/arranque-para-el-instituto/apply-progress`): empaquetar un instalador o
un servicio de Windows. Este comando sigue asumiendo una instalación editable
del repositorio clonado (`pip install -e .`) -- IT hace ese paso una vez;
después el operador sólo usa este comando y un archivo de configuración.

Por qué se cargan los scripts viejos por RUTA (`_cargar_script`) en vez de
importarlos como paquete o migrar su lógica a `src/`: `scripts/` no forma
parte del wheel instalado (`pyproject.toml`,
`[tool.hatch.build.targets.wheel]` sólo empaqueta `src/anonimizacion`) y hay
un PR abierto (#40, `feat/acceso-al-panel`) tocando
`scripts/servir_panel.py` -- mover su lógica acá hoy sería conflicto
garantizado para cero beneficio real. Este módulo reutiliza exactamente el
mismo patrón que ya usan `tests/scripts/test_procesar_carpeta.py` y
`test_servir_panel.py` (`importlib.util.spec_from_file_location`) para cargar
el script por ruta absoluta y traduce la configuración resuelta (archivo +
banderas) al mismo `sys.argv` que esos scripts ya interpretan -- CERO cambios
a `scripts/procesar_carpeta.py` ni a `scripts/servir_panel.py`. Cuando el PR
#40 mergee y la superficie de `servir_panel.py` se estabilice, migrar su
composición a `src/anonimizacion/web/` deja de tener el costo de conflicto
que tiene hoy -- pero eso es una decisión para otro cambio, no para éste.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

from anonimizacion.configuracion import ConfiguracionOperador, ErrorConfiguracion, cargar_configuracion
from anonimizacion.diagnostico import Hallazgo, diagnosticar
from anonimizacion.dominio.errores import ErrorParseo
from anonimizacion.esqueleto import Esqueleto, FixtureParseable, generar_esqueleto, generar_fixture_parseable
from anonimizacion.extraccion.texto_pymupdf import extraer_texto

_RAIZ_REPO = Path(__file__).resolve().parents[2]


def _cargar_script(nombre_archivo: str) -> ModuleType:
    """Carga `scripts/<nombre_archivo>` por ruta -- ver el docstring del módulo."""
    ruta = _RAIZ_REPO / "scripts" / nombre_archivo
    spec = importlib.util.spec_from_file_location(f"_anonimizacion_cli_{ruta.stem}", ruta)
    if spec is None or spec.loader is None:  # pragma: no cover -- sólo si el archivo desaparece
        raise RuntimeError(f"No se pudo cargar '{ruta}': revisar que el archivo exista.")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _reportar_diagnostico(hallazgos: list[Hallazgo]) -> bool:
    """Imprime TODOS los hallazgos (ok y error) para que el operador vea de
    una vez todo lo que falta, no un problema a la vez en sucesivos intentos
    fallidos. Devuelve `True` sólo si no hay ningún error."""
    todo_ok = True
    for hallazgo in hallazgos:
        etiqueta = "OK   " if hallazgo.ok else "FALTA"
        print(f"[{etiqueta}] {hallazgo.mensaje}", file=sys.stderr)
        if not hallazgo.ok:
            todo_ok = False
    return todo_ok


def _resolver(valor_cli: object, valor_config: object) -> object:
    return valor_cli if valor_cli is not None else valor_config


def _cargar_config_o_none(ruta: Path | None) -> ConfiguracionOperador | None:
    try:
        return cargar_configuracion(ruta)
    except ErrorConfiguracion as error:
        print(f"No se puede continuar: {error}", file=sys.stderr)
        return None


def _agregar_argumentos_comunes(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", type=Path, default=None, help="ruta al archivo de configuración (default: ./anonimizacion.toml)"
    )
    parser.add_argument("--db-url", default=None, help="URL de Postgres (sobrescribe el archivo de configuración)")


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anonimizacion", description="Pipeline de anonimización clínica -- punto de entrada único."
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    p_diagnosticar = subparsers.add_parser(
        "diagnosticar", help="Verifica que todo lo necesario para operar esté en orden."
    )
    _agregar_argumentos_comunes(p_diagnosticar)
    p_diagnosticar.add_argument("--entrada", type=Path, default=None, help="si se indica, también valida esta carpeta")
    p_diagnosticar.add_argument(
        "--para-red", action="store_true", help="valida también lo necesario para exponer el panel a la red"
    )

    p_procesar = subparsers.add_parser("procesar", help="Procesa una carpeta de PDFs de punta a punta.")
    _agregar_argumentos_comunes(p_procesar)
    p_procesar.add_argument("--entrada", type=Path, default=None, help="carpeta con los PDFs a procesar")
    p_procesar.add_argument("--procesos", type=int, default=None, help="grado de concurrencia")

    p_esqueleto = subparsers.add_parser(
        "esqueleto",
        help="Genera un fixture de texto sin PII a partir de un PDF real (allowlist estructural, ver esqueleto.py).",
    )
    p_esqueleto.add_argument("pdf", type=Path, help="ruta a un PDF real -- nunca se copia ni se versiona")
    p_esqueleto.add_argument(
        "--salida", type=Path, default=None, help="archivo donde escribir el esqueleto (default: stdout)"
    )
    # Opción, no subcomando: ambos modos comparten el 100% del resto del
    # pipeline (extraer el PDF, resolver --salida, reportar errores sin ruta
    # cruda) -- lo único que cambia es la función de sustitución dentro de
    # `esqueleto.py` (`enmascarar_por_forma` vs. `sustituir_por_valores_plausibles`,
    # misma allowlist estructural para ambas). Un subcomando nuevo duplicaría
    # el parsing de `pdf`/`--salida` para cero beneficio real.
    p_esqueleto.add_argument(
        "--modo",
        choices=("enmascarado", "parseable"),
        default="enmascarado",
        help=(
            "'enmascarado' (default): letras/dígitos tapados por forma -- sólo prueba detección de tipo y "
            "layout. 'parseable': valores sintéticos plausibles (fechas válidas y coherentes, "
            "nombres/números con la misma forma) que un parser puede leer de punta a punta."
        ),
    )

    p_servir = subparsers.add_parser("servir", help="Levanta el panel de operación.")
    _agregar_argumentos_comunes(p_servir)
    p_servir.add_argument("--puerto", type=int, default=None)
    p_servir.add_argument("--raiz", type=Path, default=None, help="raíz autorizada para lanzar corridas nuevas")
    p_servir.add_argument("--procesos", type=int, default=None, help="grado de concurrencia de cada corrida")
    p_servir.add_argument(
        "--escuchar-red",
        action="store_true",
        default=False,
        help="expone el panel a toda la red del instituto (default: sólo 127.0.0.1)",
    )

    return parser


def _comando_diagnosticar(args: argparse.Namespace) -> int:
    config = _cargar_config_o_none(args.config)
    if config is None:
        return 1
    config = replace(
        config,
        db_url=_resolver(args.db_url, config.db_url),
        entrada=_resolver(args.entrada, config.entrada),
    )

    hallazgos = diagnosticar(config, requiere_entrada=config.entrada is not None, requiere_red=args.para_red)
    if _reportar_diagnostico(hallazgos):
        print("Todo en orden.", file=sys.stderr)
        return 0
    return 1


def _comando_procesar(args: argparse.Namespace) -> int:
    config = _cargar_config_o_none(args.config)
    if config is None:
        return 1
    entrada = _resolver(args.entrada, config.entrada)
    db_url = _resolver(args.db_url, config.db_url)
    procesos = _resolver(args.procesos, config.procesos)
    config = replace(config, entrada=entrada, db_url=db_url, procesos=procesos)

    hallazgos = diagnosticar(config, requiere_entrada=True, requiere_red=False)
    if not _reportar_diagnostico(hallazgos):
        print("No se puede procesar: resolver lo anterior antes de reintentar.", file=sys.stderr)
        return 1

    modulo = _cargar_script("procesar_carpeta.py")
    argv = [
        "procesar_carpeta.py",
        "--entrada",
        str(entrada),
        "--db-url",
        str(db_url),
        "--procesos",
        str(procesos),
    ]
    argv_original = sys.argv
    sys.argv = argv
    try:
        return modulo.main()
    finally:
        sys.argv = argv_original


def _comando_esqueleto(args: argparse.Namespace) -> int:
    """No requiere `--config`/`--db-url` ni `diagnosticar`: es una herramienta
    de lectura local, sin tocar la base de datos ni la cola -- el operador la
    corre directo sobre sus PDFs reales, que nunca se copian al repositorio.
    """
    try:
        texto = extraer_texto(args.pdf)
    except ErrorParseo as error:
        # Nunca la ruta cruda del PDF acá (mismo principio que
        # `dominio/errores.py`: sin mensajes crudos ni rutas de archivo).
        print(f"No se pudo extraer texto del PDF: {error.codigo.value}", file=sys.stderr)
        return 1

    resultado: Esqueleto | FixtureParseable
    resultado = generar_fixture_parseable(texto) if args.modo == "parseable" else generar_esqueleto(texto)
    contenido = resultado.formatear()
    if args.salida is not None:
        args.salida.write_text(contenido, encoding="utf-8")
        print(f"Esqueleto escrito en '{args.salida}'.", file=sys.stderr)
    else:
        print(contenido)

    if isinstance(resultado, Esqueleto):
        print(
            f"Tipo detectado: {resultado.tipo_detectado.value} "
            f"({resultado.puntaje}/{resultado.total_marcadores} marcadores de firma).",
            file=sys.stderr,
        )
    else:
        print(f"Tipo detectado: {resultado.tipo_detectado.value}.", file=sys.stderr)
    return 0


def _comando_servir(args: argparse.Namespace) -> int:
    config = _cargar_config_o_none(args.config)
    if config is None:
        return 1
    db_url = _resolver(args.db_url, config.db_url)
    puerto = _resolver(args.puerto, config.puerto)
    raiz = _resolver(args.raiz, config.raiz)
    procesos = _resolver(args.procesos, config.procesos)
    escuchar_red = args.escuchar_red or config.escuchar_red
    config = replace(config, db_url=db_url, puerto=puerto, raiz=raiz, procesos=procesos, escuchar_red=escuchar_red)

    hallazgos = diagnosticar(config, requiere_entrada=False, requiere_red=escuchar_red)
    if not _reportar_diagnostico(hallazgos):
        print("No se puede levantar el panel: resolver lo anterior antes de reintentar.", file=sys.stderr)
        return 1

    modulo = _cargar_script("servir_panel.py")
    argv = [
        "servir_panel.py",
        "--db-url",
        str(db_url),
        "--puerto",
        str(puerto),
        "--raiz",
        str(raiz),
        "--procesos",
        str(procesos),
    ]
    if escuchar_red:
        argv.append("--escuchar-red")
    argv_original = sys.argv
    sys.argv = argv
    try:
        return modulo.main()
    finally:
        sys.argv = argv_original


def main(argv: list[str] | None = None) -> int:
    parser = _construir_parser()
    args = parser.parse_args(argv)

    if args.comando == "diagnosticar":
        return _comando_diagnosticar(args)
    if args.comando == "procesar":
        return _comando_procesar(args)
    if args.comando == "esqueleto":
        return _comando_esqueleto(args)
    if args.comando == "servir":
        return _comando_servir(args)

    parser.print_help(sys.stderr)  # pragma: no cover -- argparse ya exige un subcomando válido
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
