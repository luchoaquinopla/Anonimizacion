"""Punto de entrada único instalable: composition root con subcomandos
(`diagnosticar`/`procesar`/`esqueleto`/`exportar`/`servir`). Resuelve banderas/config y
llama a `comandos.procesar.ejecutar(...)`/`comandos.servir.servir(...)` con argumentos
con nombre -- no carga nada por ruta ni re-parsea `sys.argv`. Instalador/servicio de
Windows fuera de alcance (ver `sdd/arranque-para-el-instituto/apply-progress`)."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from anonimizacion.comandos import procesar as comandos_procesar
from anonimizacion.comandos import servir as comandos_servir
from anonimizacion.configuracion import ConfiguracionOperador, ErrorConfiguracion, cargar_configuracion
from anonimizacion.diagnostico import Hallazgo, diagnosticar
from anonimizacion.dominio.errores import ErrorParseo
from anonimizacion.esqueleto import Esqueleto, FixtureParseable, generar_esqueleto, generar_fixture_parseable
from anonimizacion.extraccion.texto_pymupdf import extraer_texto
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pseudonimizacion.almacen_pepper import obtener_pepper
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.salida.exportacion import TAMANO_PAGINA_DEFECTO, exportar_dataset
from anonimizacion.trabajadores.despacho_paralelo import validar_grado_concurrencia


def _reportar_diagnostico(hallazgos: list[Hallazgo]) -> bool:
    """Imprime todos los hallazgos de una vez, no uno por intento fallido.
    Devuelve `True` sólo si no hay ningún error."""
    todo_ok = True
    for hallazgo in hallazgos:
        etiqueta = "OK   " if hallazgo.ok else "FALTA"
        print(f"[{etiqueta}] {hallazgo.mensaje}", file=sys.stderr)
        if not hallazgo.ok:
            todo_ok = False
    return todo_ok


def _resolver(valor_cli: object, valor_config: object) -> object:
    return valor_cli if valor_cli is not None else valor_config


def _tipo_procesos(valor: str) -> int:
    """`type=` de argparse para `--procesos`: valida el tope duro una sola vez, para
    que un valor inválido falle antes de tocar Postgres/spaCy."""
    return validar_grado_concurrencia(int(valor))


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
    p_procesar.add_argument(
        "--procesos", type=_tipo_procesos, default=None, help="grado de concurrencia (tope duro validado acá)"
    )

    p_esqueleto = subparsers.add_parser(
        "esqueleto",
        help="Genera un fixture de texto sin PII a partir de un PDF real (allowlist estructural, ver esqueleto.py).",
    )
    p_esqueleto.add_argument("pdf", type=Path, help="ruta a un PDF real -- nunca se copia ni se versiona")
    p_esqueleto.add_argument(
        "--salida", type=Path, default=None, help="archivo donde escribir el esqueleto (default: stdout)"
    )
    # Opción, no subcomando: ambos modos comparten el resto del pipeline, sólo
    # cambia la función de sustitución dentro de esqueleto.py.
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

    p_exportar = subparsers.add_parser(
        "exportar",
        help="Exporta el dataset vinculado (Parquet + manifiesto) desde PostgreSQL, sin mutar la base.",
    )
    _agregar_argumentos_comunes(p_exportar)
    p_exportar.add_argument("--salida", type=Path, required=True, help="carpeta donde escribir el dataset exportado")
    p_exportar.add_argument(
        "--tamano-pagina",
        type=int,
        default=TAMANO_PAGINA_DEFECTO,
        help=f"episodios por página de streaming (default: {TAMANO_PAGINA_DEFECTO})",
    )

    p_servir = subparsers.add_parser("servir", help="Levanta el panel de operación.")
    _agregar_argumentos_comunes(p_servir)
    p_servir.add_argument("--puerto", type=int, default=None)
    p_servir.add_argument("--raiz", type=Path, default=None, help="raíz autorizada para lanzar corridas nuevas")
    p_servir.add_argument(
        "--procesos", type=_tipo_procesos, default=None, help="grado de concurrencia de cada corrida (tope duro validado acá)"
    )
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

    print("Pepper: cargando desde ANONIMIZACION_PEPPER...", file=sys.stderr)
    pepper = obtener_pepper()

    # motor sólo se carga acá para el camino secuencial: con procesos>1 cada hijo
    # arma su propio MotorPii (~875 MB) -- cargarlo también acá sería una copia de más.
    motor: MotorPii | None = None
    if procesos <= 1:
        print("Motor de PII: cargando modelo de spaCy (puede tardar unos segundos)...", file=sys.stderr)
        motor = MotorPii()
    else:
        print(
            f"Motor de PII: se carga en cada uno de los {procesos} procesos hijos, no en este proceso.",
            file=sys.stderr,
        )

    print(f"Conectando a Postgres: {db_url}", file=sys.stderr)
    engine = construir_engine_postgres(str(db_url))

    return comandos_procesar.ejecutar(
        entrada=entrada,
        engine=engine,
        motor=motor,
        pepper=pepper,
        procesos=procesos,
        db_url=str(db_url),
    )


def _comando_esqueleto(args: argparse.Namespace) -> int:
    """No requiere `--config`/`--db-url` ni `diagnosticar`: herramienta de lectura
    local que el operador corre directo sobre PDFs que nunca se copian al repo."""
    try:
        texto = extraer_texto(args.pdf)
    except ErrorParseo as error:
        # Nunca la ruta cruda del PDF acá (sin mensajes crudos ni rutas de archivo).
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


def _comando_exportar(args: argparse.Namespace) -> int:
    """Exporta el dataset vinculado. Sin `diagnosticar`: no procesa PDFs, sólo lee
    `db_url` (validada implícitamente por `exportar_dataset` al conectar)."""
    config = _cargar_config_o_none(args.config)
    if config is None:
        return 1
    db_url = _resolver(args.db_url, config.db_url)

    engine = construir_engine_postgres(str(db_url))
    try:
        resumen = exportar_dataset(engine, args.salida, tamano_pagina=args.tamano_pagina)
    finally:
        engine.dispose()

    print(
        f"Exportación completa en '{args.salida}': "
        f"{resumen.episodios} episodios, {resumen.ecg} ECG, "
        f"{resumen.laboratorio} resultados de laboratorio, {resumen.eco} eco.",
        file=sys.stderr,
    )
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

    return comandos_servir.servir(
        db_url=str(db_url),
        puerto=puerto,
        raiz=Path(raiz),
        procesos=procesos,
        escuchar_red=escuchar_red,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _construir_parser()
    args = parser.parse_args(argv)

    if args.comando == "diagnosticar":
        return _comando_diagnosticar(args)
    if args.comando == "procesar":
        return _comando_procesar(args)
    if args.comando == "esqueleto":
        return _comando_esqueleto(args)
    if args.comando == "exportar":
        return _comando_exportar(args)
    if args.comando == "servir":
        return _comando_servir(args)

    parser.print_help(sys.stderr)  # pragma: no cover -- argparse ya exige un subcomando válido
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
