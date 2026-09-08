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
    LONGITUD_MINIMA_SECRETO,
    VAR_ENV_ARCHIVO_SECRETO,
    VAR_ENV_SECRETO,
    ErrorSecretoPanelArchivoIlegible,
    ErrorSecretoPanelInvalido,
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
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-inicial-valido")
    primero = obtener_secreto_panel()

    # cambiar la variable de entorno no debe afectar un secreto ya cacheado
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-cambiado")
    segundo = obtener_secreto_panel()

    assert primero == segundo == b"secreto-inicial-valido"


def test_secreto_por_debajo_del_piso_minimo_es_invalido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revisión de seguridad (hallazgo ALTA): un secreto corto no protege
    nada -- se rechaza con un error tipado y distinto de "no configurado",
    para que quien administra el servidor sepa que SÍ intentó configurar
    algo, pero no alcanza."""
    monkeypatch.setenv(VAR_ENV_SECRETO, "x" * (LONGITUD_MINIMA_SECRETO - 1))

    with pytest.raises(ErrorSecretoPanelInvalido):
        obtener_secreto_panel()


def test_un_solo_espacio_como_secreto_es_invalido_no_no_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduce el hallazgo ALTA tal cual se reportó: `ANONIMIZACION_PANEL_SECRETO=" "`
    (un solo espacio) NO puede colarse como "hay secreto configurado" --
    tiene que caer en `ErrorSecretoPanelInvalido`, no en
    `ErrorSecretoPanelNoConfigurado` (que en `servir_panel.py` se tolera en
    modo loopback): un valor no vacío es una señal de que alguien SÍ trató
    de configurar un secreto, y hacerlo mal tiene que fallar fuerte, no
    degradarse en silencio a "como si nada estuviera configurado"."""
    monkeypatch.setenv(VAR_ENV_SECRETO, " ")

    with pytest.raises(ErrorSecretoPanelInvalido):
        obtener_secreto_panel()


def test_variable_de_entorno_recorta_salto_de_linea_final(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revisión de seguridad (hallazgo MEDIA): antes sólo la fuente de
    archivo recortaba espacios en blanco -- un `.env` mal generado (o
    ciertos entornos de Windows que preservan CRLF) con
    `ANONIMIZACION_PANEL_SECRETO=secreto-valido-de-verdad\\n` hacía que el
    secreto cargado nunca coincidiera con lo que el médico tipeaba, sin
    ningún mensaje que lo explicara. Las dos fuentes recortan igual ahora."""
    monkeypatch.setenv(VAR_ENV_SECRETO, "secreto-valido-de-verdad\n")

    secreto = obtener_secreto_panel()

    assert secreto == b"secreto-valido-de-verdad"


def test_archivo_con_secreto_corto_es_invalido(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    ruta_secreto = tmp_path / "panel.secreto"  # type: ignore[attr-defined]
    ruta_secreto.write_text("corto", encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_ARCHIVO_SECRETO, str(ruta_secreto))

    with pytest.raises(ErrorSecretoPanelInvalido):
        obtener_secreto_panel()


def test_archivo_con_solo_salto_de_linea_es_invalido(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """Mismo criterio que la variable de entorno: un archivo con CONTENIDO
    (aunque sea sólo un salto de línea) es una fuente CONFIGURADA -- si
    recorta a algo por debajo del piso mínimo, es inválido, no "no
    configurado". Distinto de un archivo totalmente vacío (ver el test de
    abajo), que sí se trata como fuente ausente."""
    ruta_secreto = tmp_path / "panel.secreto"  # type: ignore[attr-defined]
    ruta_secreto.write_text("\n", encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_ARCHIVO_SECRETO, str(ruta_secreto))

    with pytest.raises(ErrorSecretoPanelInvalido):
        obtener_secreto_panel()


def test_archivo_totalmente_vacio_se_trata_como_no_configurado(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    ruta_secreto = tmp_path / "panel.secreto"  # type: ignore[attr-defined]
    ruta_secreto.write_text("", encoding="utf-8")
    monkeypatch.setenv(VAR_ENV_ARCHIVO_SECRETO, str(ruta_secreto))

    with pytest.raises(ErrorSecretoPanelNoConfigurado):
        obtener_secreto_panel()


def test_archivo_inexistente_no_revienta_con_traza_cruda(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """Revisión de seguridad (hallazgo BAJA): una ruta mal configurada tiene
    que fallar con un error tipado y claro, no con un `FileNotFoundError`
    crudo sin capturar en ningún lado -- mismo estándar de "fallar temprano
    y claro" que el resto del módulo."""
    ruta_inexistente = tmp_path / "no-existe" / "panel.secreto"  # type: ignore[attr-defined]
    monkeypatch.setenv(VAR_ENV_ARCHIVO_SECRETO, str(ruta_inexistente))

    with pytest.raises(ErrorSecretoPanelArchivoIlegible):
        obtener_secreto_panel()


def test_repr_del_error_invalido_nunca_incluye_el_valor_del_secreto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR_ENV_SECRETO, "corto-y-no-debe-aparecer")
    monkeypatch.setenv(VAR_ENV_SECRETO, "x" * (LONGITUD_MINIMA_SECRETO - 1))

    try:
        obtener_secreto_panel()
    except ErrorSecretoPanelInvalido as error:
        assert "x" * (LONGITUD_MINIMA_SECRETO - 1) not in repr(error)
        assert "x" * (LONGITUD_MINIMA_SECRETO - 1) not in str(error)


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
