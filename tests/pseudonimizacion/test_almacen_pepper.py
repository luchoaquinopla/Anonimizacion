"""Tests de `almacen_pepper.py` (spec `patient-pseudonymization`): carga del pepper.

El pepper de test es SIEMPRE un valor fijo sintético -- nunca se lee de
infraestructura real (Vault/KMS) en la suite.
"""

from __future__ import annotations

import pytest

from anonimizacion.pseudonimizacion.almacen_pepper import (
    VAR_ENV_ARCHIVO_PEPPER,
    VAR_ENV_PEPPER,
    ErrorPepperNoConfigurado,
    obtener_pepper,
)


@pytest.fixture(autouse=True)
def _limpiar_cache_y_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VAR_ENV_PEPPER, raising=False)
    monkeypatch.delenv(VAR_ENV_ARCHIVO_PEPPER, raising=False)
    obtener_pepper.cache_clear()
    yield
    obtener_pepper.cache_clear()


def test_carga_pepper_desde_variable_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_ENV_PEPPER, "pepper-sintetico-de-test")

    pepper = obtener_pepper()

    assert pepper == b"pepper-sintetico-de-test"


def test_carga_pepper_desde_archivo_si_no_hay_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    ruta_pepper = tmp_path / "pepper.secreto"  # type: ignore[attr-defined]
    ruta_pepper.write_text("pepper-de-archivo-sintetico\n", encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_ARCHIVO_PEPPER, str(ruta_pepper))

    pepper = obtener_pepper()

    assert pepper == b"pepper-de-archivo-sintetico"


def test_variable_de_entorno_tiene_prioridad_sobre_archivo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    ruta_pepper = tmp_path / "pepper.secreto"  # type: ignore[attr-defined]
    ruta_pepper.write_text("pepper-de-archivo", encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_ARCHIVO_PEPPER, str(ruta_pepper))
    monkeypatch.setenv(VAR_ENV_PEPPER, "pepper-de-variable")

    pepper = obtener_pepper()

    assert pepper == b"pepper-de-variable"


def test_sin_pepper_configurado_lanza_error_tipado() -> None:
    with pytest.raises(ErrorPepperNoConfigurado):
        obtener_pepper()


def test_pepper_se_carga_una_sola_vez_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_ENV_PEPPER, "pepper-inicial")
    primero = obtener_pepper()

    # cambiar la variable de entorno no debe afectar un pepper ya cacheado
    monkeypatch.setenv(VAR_ENV_PEPPER, "pepper-cambiado")
    segundo = obtener_pepper()

    assert primero == segundo == b"pepper-inicial"


def test_repr_del_error_nunca_incluye_el_valor_del_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_ENV_PEPPER, "pepper-secreto-no-debe-aparecer")
    obtener_pepper()  # cachea con este valor

    obtener_pepper.cache_clear()
    monkeypatch.delenv(VAR_ENV_PEPPER, raising=False)

    try:
        obtener_pepper()
    except ErrorPepperNoConfigurado as error:
        assert "pepper-secreto-no-debe-aparecer" not in repr(error)
        assert "pepper-secreto-no-debe-aparecer" not in str(error)
