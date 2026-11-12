"""Caracterización del contrato del CLI `anonimizacion` (Entrega 0, Requisito 2).

Fija, para cada subcomando, el conjunto de banderas aceptadas por `argparse`,
los valores por defecto EFECTIVOS que llegan a la lógica de negocio, y el
código de salida para al menos un caso de éxito y uno de error. No afirma
nada sobre `_cargar_script`/`sys.argv`/el doble `argparse` (E4 los elimina;
este archivo tiene que sobrevivir intacto a esa entrega -- `design.md`, D1).
"""

from __future__ import annotations


import pytest

from anonimizacion import cli
from anonimizacion.configuracion import ConfiguracionOperador
from anonimizacion.diagnostico import Hallazgo
from anonimizacion.trabajadores.despacho_paralelo import grado_de_concurrencia_por_defecto

pytestmark = pytest.mark.caracterizacion


def _banderas(subcomando: str) -> set[str]:
    parser = cli._construir_parser()
    for accion in parser._subparsers._group_actions:  # type: ignore[union-attr]
        if subcomando in accion.choices:
            subparser = accion.choices[subcomando]
            return {
                cadena
                for accion_hija in subparser._actions
                for cadena in accion_hija.option_strings
            }
    raise AssertionError(f"subcomando desconocido: {subcomando}")


def test_banderas_aceptadas_por_subcomando() -> None:
    assert _banderas("diagnosticar") == {"-h", "--help", "--config", "--db-url", "--entrada", "--para-red"}
    assert _banderas("procesar") == {"-h", "--help", "--config", "--db-url", "--entrada", "--procesos"}
    assert _banderas("esqueleto") == {"-h", "--help", "--salida", "--modo"}
    assert _banderas("exportar") == {"-h", "--help", "--config", "--db-url", "--salida", "--tamano-pagina"}
    assert _banderas("servir") == {
        "-h",
        "--help",
        "--config",
        "--db-url",
        "--puerto",
        "--raiz",
        "--procesos",
        "--escuchar-red",
    }


def test_esqueleto_default_de_modo_es_enmascarado() -> None:
    parser = cli._construir_parser()
    args = parser.parse_args(["esqueleto", "cualquier.pdf"])
    assert args.modo == "enmascarado"
    assert args.salida is None


def test_exportar_requiere_salida_y_tiene_tamano_pagina_por_defecto() -> None:
    from anonimizacion.salida.exportacion import TAMANO_PAGINA_DEFECTO

    parser = cli._construir_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["exportar"])  # --salida es requerido

    args = parser.parse_args(["exportar", "--salida", "/tmp/out"])
    assert args.tamano_pagina == TAMANO_PAGINA_DEFECTO


def test_procesar_sin_banderas_resuelve_los_defaults_de_configuracion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escenario "banderas y defaults de `procesar`": sin `anonimizacion.toml`
    ni banderas, los valores EFECTIVOS que le llegan a la lógica de negocio
    deben ser exactamente los de `ConfiguracionOperador()` por defecto.

    Corrección (auditoria-y-poda, E4): antes se afirmaba armando el `argv` de
    un script cargado por ruta -- afirmaba el MECANISMO (`_cargar_script`/
    `sys.argv`), no la superficie observable que D1 exige y que el docstring
    del módulo dice fijar. Se corrige interceptando `diagnosticar`, el punto
    donde la configuración YA resuelta se hace visible -- ese punto no
    depende de cómo se ejecute el procesamiento después, así que sobrevive a
    E4 sin volver a romperse."""
    capturado: dict[str, object] = {}

    def _diagnosticar_espia(config, *, requiere_entrada, requiere_red):
        capturado["config"] = config
        # Corta acá a propósito: lo único que interesa es la config resuelta
        # que YA le llegó a este punto, no lo que pasa después.
        return [Hallazgo(ok=False, mensaje="corte deliberado del test -- sólo interesa la config resuelta")]

    monkeypatch.setattr(cli, "diagnosticar", _diagnosticar_espia)
    # Fuerza "no hay anonimizacion.toml en el cwd" sin depender del directorio real.
    monkeypatch.setattr(cli, "_cargar_config_o_none", lambda ruta: ConfiguracionOperador())

    codigo = cli.main(["procesar", "--entrada", "carpeta"])

    assert codigo == 1
    config = capturado["config"]
    defaults = ConfiguracionOperador()
    assert str(config.entrada) == "carpeta"
    assert config.db_url == defaults.db_url
    assert config.procesos == defaults.procesos
    assert defaults.procesos == grado_de_concurrencia_por_defecto()


def test_diagnosticar_devuelve_0_si_todo_esta_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_cargar_config_o_none", lambda ruta: ConfiguracionOperador())
    monkeypatch.setattr(cli, "diagnosticar", lambda config, *, requiere_entrada, requiere_red: [Hallazgo(ok=True, mensaje="ok")])

    assert cli.main(["diagnosticar"]) == 0


def test_diagnosticar_devuelve_1_si_hay_un_hallazgo_en_falta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_cargar_config_o_none", lambda ruta: ConfiguracionOperador())
    monkeypatch.setattr(
        cli, "diagnosticar", lambda config, *, requiere_entrada, requiere_red: [Hallazgo(ok=False, mensaje="falta algo")]
    )

    assert cli.main(["diagnosticar"]) == 1


def test_procesar_devuelve_1_sin_ejecutar_trabajo_si_el_diagnostico_falla(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Si el diagnóstico encuentra un problema, `procesar` corta ANTES de
    hacer ningún trabajo real.

    Corrección (auditoria-y-poda, E4): la garantía observable es "no ejecutó
    el procesamiento", no "no llamó a `_cargar_script`" -- esa segunda forma
    de decirlo está atada al mecanismo que E4 elimina. No se mockea nada del
    camino de procesamiento a propósito: si `procesar` alguna vez llegara a
    ejecutarlo sin que el diagnóstico esté en orden, este test lo detecta
    porque ese camino real (pepper/Postgres) no está disponible en el
    entorno de test y el `codigo`/mensaje esperados no aparecen."""
    monkeypatch.setattr(cli, "_cargar_config_o_none", lambda ruta: ConfiguracionOperador())
    monkeypatch.setattr(
        cli, "diagnosticar", lambda config, *, requiere_entrada, requiere_red: [Hallazgo(ok=False, mensaje="falta algo")]
    )

    codigo = cli.main(["procesar", "--entrada", "carpeta"])

    assert codigo == 1
    salida = capsys.readouterr().err
    assert "No se puede procesar" in salida
