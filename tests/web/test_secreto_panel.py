"""Tests de `secreto_panel.py`: carga del secreto compartido del panel.

Mismo patrón que `tests/pseudonimizacion/test_almacen_pepper.py` a propósito
(dos fuentes con la misma precedencia, mismo cacheo, mismo "nunca se filtra
el valor") -- pero es un módulo DISTINTO y un secreto DISTINTO: el pepper
HMAC es de pseudonimización, este es de sesión del panel. No se comparten
(instrucción explícita de la tarea).
"""

from __future__ import annotations

import pytest

from anonimizacion.web.secreto_panel import (
    VAR_ENV_ARCHIVO_SECRETO,
    VAR_ENV_SECRETO,
    ErrorSecretoPanelNoConfigurado,
    obtener_secreto_panel,
)


@pytest.fixture(autouse=True)
def _limpiar_cache_y_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VAR_ENV_SECRETO, raising=False)
    monkeypatch.delenv(VAR_ENV_ARCHIVO_SECRETO, raising=False)
    obtener_secreto_panel.cache_clear()
    yield
    obtener_secreto_panel.cache_clear()


def test_carga_secreto_desde_variable_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-sintetico-de-test")

    secreto = obtener_secreto_panel()

    assert secreto == b"secreto-sintetico-de-test"


def test_carga_secreto_desde_archivo_si_no_hay_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    ruta_secreto = tmp_path / "panel.secreto"  # type: ignore[attr-defined]
    ruta_secreto.write_text("secreto-de-archivo-sintetico\n", encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_ARCHIVO_SECRETO, str(ruta_secreto))

    secreto = obtener_secreto_panel()

    assert secreto == b"secreto-de-archivo-sintetico"


def test_variable_de_entorno_tiene_prioridad_sobre_archivo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    ruta_secreto = tmp_path / "panel.secreto"  # type: ignore[attr-defined]
    ruta_secreto.write_text("secreto-de-archivo", encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_ARCHIVO_SECRETO, str(ruta_secreto))
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-de-variable")

    secreto = obtener_secreto_panel()

    assert secreto == b"secreto-de-variable"


def test_sin_secreto_configurado_lanza_error_tipado() -> None:
    with pytest.raises(ErrorSecretoPanelNoConfigurado):
        obtener_secreto_panel()


def test_secreto_se_carga_una_sola_vez_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-inicial")
    primero = obtener_secreto_panel()

    # cambiar la variable de entorno no debe afectar un secreto ya cacheado
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-cambiado")
    segundo = obtener_secreto_panel()

    assert primero == segundo == b"secreto-inicial"


def test_repr_del_error_nunca_incluye_el_valor_del_secreto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-no-debe-aparecer")
    obtener_secreto_panel()  # cachea con este valor

    obtener_secreto_panel.cache_clear()
    monkeypatch.delenv(VAR_ENV_SECRETO, raising=False)

    try:
        obtener_secreto_panel()
    except ErrorSecretoPanelNoConfigurado as error:
        assert "secreto-no-debe-aparecer" not in repr(error)
        assert "secreto-no-debe-aparecer" not in str(error)
