"""Tests de `anonimizacion.configuracion` (composition root, arranque-para-el-instituto).

El archivo de configuración reemplaza a las banderas de línea de comandos y a
variables de entorno sueltas para valores NO secretos (URL de base, carpeta
de entrada, puerto, etc.). Los secretos (pepper HMAC, secreto del panel)
siguen viniendo SIEMPRE de variable de entorno o archivo aparte -- nunca de
acá (ver docstring del módulo para el porqué).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anonimizacion.configuracion import (
    ConfiguracionOperador,
    ErrorConfiguracionClaveDesconocida,
    ErrorConfiguracionInvalida,
    ErrorConfiguracionNoEncontrada,
    ErrorConfiguracionSecretoEnArchivo,
    ErrorConfiguracionTipoInvalido,
    VAR_ENV_RUTA_CONFIG,
    cargar_configuracion,
)


def test_sin_archivo_en_la_ruta_por_defecto_usa_los_valores_de_produccion(monkeypatch, tmp_path) -> None:
    """El archivo de configuración es OPCIONAL: un médico que todavía no
    escribió ninguno tiene que poder correr `anonimizacion diagnosticar`
    igual, con los mismos defaults que ya usaban los dos scripts."""
    monkeypatch.chdir(tmp_path)

    config = cargar_configuracion(None)

    assert config == ConfiguracionOperador()
    assert config.entrada is None
    assert config.escuchar_red is False


def test_archivo_explicito_que_no_existe_falla_claro(tmp_path) -> None:
    ruta = tmp_path / "no-existe.toml"

    with pytest.raises(ErrorConfiguracionNoEncontrada) as excinfo:
        cargar_configuracion(ruta)

    mensaje = str(excinfo.value)
    assert str(ruta) in mensaje
    assert "no se encontr" in mensaje.lower()


def test_carga_los_valores_del_archivo_con_los_tipos_correctos(tmp_path) -> None:
    ruta = tmp_path / "anonimizacion.toml"
    ruta.write_text(
        """
        db_url = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
        entrada = "D:/pdfs-instituto"
        raiz = "D:/pdfs-instituto"
        puerto = 9000
        procesos = 3
        escuchar_red = true
        """,
        encoding="utf-8",
    )

    config = cargar_configuracion(ruta)

    assert config.db_url == "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
    assert config.entrada == Path("D:/pdfs-instituto")
    assert config.raiz == Path("D:/pdfs-instituto")
    assert config.puerto == 9000
    assert config.procesos == 3
    assert config.escuchar_red is True


def test_usa_la_ruta_indicada_por_variable_de_entorno_si_no_se_pasa_ruta_explicita(monkeypatch, tmp_path) -> None:
    ruta = tmp_path / "config-institucional.toml"
    ruta.write_text('puerto = 9500\n', encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_RUTA_CONFIG, str(ruta))

    config = cargar_configuracion(None)

    assert config.puerto == 9500


@pytest.mark.parametrize("clave_secreto", ["pepper", "secreto", "anonimizacion_pepper", "anonimizacion_panel_secreto", "password"])
def test_rechaza_secretos_en_el_archivo_de_configuracion(tmp_path, clave_secreto: str) -> None:
    """Los secretos no se degradan: si alguien intenta poner el pepper o el
    secreto del panel en este archivo (que puede terminar versionado o
    compartido), el arranque tiene que fallar fuerte, no aceptarlo."""
    ruta = tmp_path / "anonimizacion.toml"
    ruta.write_text(f'{clave_secreto} = "algo-que-no-deberia-estar-aca"\n', encoding="utf-8")

    with pytest.raises(ErrorConfiguracionSecretoEnArchivo) as excinfo:
        cargar_configuracion(ruta)

    mensaje = str(excinfo.value)
    assert clave_secreto in mensaje
    assert "variable de entorno" in mensaje.lower()


def test_rechaza_una_clave_desconocida_con_un_error_de_tipeo(tmp_path) -> None:
    """Caso real de operador: escribe `puertos` (con 's') en vez de `puerto`."""
    ruta = tmp_path / "anonimizacion.toml"
    ruta.write_text("puertos = 9000\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionClaveDesconocida) as excinfo:
        cargar_configuracion(ruta)

    mensaje = str(excinfo.value)
    assert "puertos" in mensaje
    assert "puerto" in mensaje  # sugiere las claves válidas


def test_rechaza_toml_con_error_de_sintaxis(tmp_path) -> None:
    ruta = tmp_path / "anonimizacion.toml"
    ruta.write_text("puerto = [no cierra\n", encoding="utf-8")

    with pytest.raises(ErrorConfiguracionInvalida) as excinfo:
        cargar_configuracion(ruta)

    assert str(ruta) in str(excinfo.value)


def test_rechaza_un_puerto_que_no_es_numero(tmp_path) -> None:
    ruta = tmp_path / "anonimizacion.toml"
    ruta.write_text('puerto = "ocho mil"\n', encoding="utf-8")

    with pytest.raises(ErrorConfiguracionTipoInvalido) as excinfo:
        cargar_configuracion(ruta)

    mensaje = str(excinfo.value)
    assert "puerto" in mensaje


def test_rechaza_escuchar_red_que_no_es_booleano(tmp_path) -> None:
    ruta = tmp_path / "anonimizacion.toml"
    ruta.write_text('escuchar_red = "si"\n', encoding="utf-8")

    with pytest.raises(ErrorConfiguracionTipoInvalido):
        cargar_configuracion(ruta)


def _cargar_script_por_ruta(nombre_archivo: str):
    """Mismo patrón que `tests/scripts/test_procesar_carpeta.py::_cargar_script`."""
    import importlib.util

    raiz_repo = Path(__file__).resolve().parents[1]
    ruta = raiz_repo / "scripts" / nombre_archivo
    spec = importlib.util.spec_from_file_location(f"_config_vs_{ruta.stem}", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_el_default_de_db_url_no_diverge_silenciosamente_de_los_dos_scripts() -> None:
    """Los dos scripts sueltos (`procesar_carpeta.py`, `servir_panel.py`)
    siguen existiendo con su propio `_DB_URL_DEFAULT` cada uno -- ver el
    docstring de `anonimizacion.cli`. Los tres literales son idénticos HOY
    porque nadie los desincronizó todavía, no porque compartan una única
    fuente: este centinela falla el día que alguien cambie uno solo de los
    tres y se olvide de los otros dos."""
    procesar = _cargar_script_por_ruta("procesar_carpeta.py")
    servir = _cargar_script_por_ruta("servir_panel.py")

    assert ConfiguracionOperador().db_url == procesar._DB_URL_DEFAULT == servir._DB_URL_DEFAULT
