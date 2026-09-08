"""Tests de `autenticacion_panel.py`: exige HTTP Basic Auth contra un secreto
compartido, envolviendo el WSGI real -- no un doble del enrutador.

Decisión (tarea `acceso-al-panel`): el panel pasó de LECTURA a poder lanzar
`POST /corridas` (horas de CPU sobre cualquier ruta bajo `--raiz`). Se elige
HTTP Basic Auth con un secreto compartido -- no usuario/contraseña
persistidos (agregaría una base de usuarios, altas, recuperación,
desproporcionado para un solo operador) ni un formulario de login a medida
(browser ya implementa el diálogo nativo de Basic Auth; un formulario propio
sería más código para el mismo cierre de riesgo). Se protege TODO el panel,
no sólo `POST /corridas`: envolver la aplicación WSGI COMPLETA (en vez de
cada ruta) es la única forma de garantizar que ninguna ruta -- ni una nueva
que se agregue después -- quede sin proteger por descuido.
"""

from __future__ import annotations

import base64
import hmac
import io
import json

import pytest

from anonimizacion.web.autenticacion_panel import exigir_autenticacion

_SECRETO = b"secreto-sintetico-de-test"


def _app_interna_espia(llamadas: list[tuple[str, str]]):
    def aplicacion(entorno, iniciar_respuesta):
        llamadas.append((entorno["REQUEST_METHOD"], entorno["PATH_INFO"]))
        cuerpo = json.dumps({"ok": True}).encode()
        iniciar_respuesta("200 OK", [("Content-Type", "application/json")])
        return [cuerpo]

    return aplicacion


def _solicitar(aplicacion, *, ruta: str = "/panel/x", metodo: str = "GET", autorizacion: str | None = None):
    estado: list[str] = []
    encabezados: list[tuple[str, str]] = []
    entorno: dict[str, object] = {
        "REQUEST_METHOD": metodo,
        "PATH_INFO": ruta,
        "wsgi.input": io.BytesIO(b""),
        "CONTENT_LENGTH": "0",
    }
    if autorizacion is not None:
        entorno["HTTP_AUTHORIZATION"] = autorizacion
    cuerpo = aplicacion(entorno, lambda codigo, headers: (estado.append(codigo), encabezados.extend(headers)))
    return estado[0], dict(encabezados), b"".join(cuerpo)


def _basic(usuario: str, contrasena: str) -> str:
    credencial = base64.b64encode(f"{usuario}:{contrasena}".encode()).decode()
    return f"Basic {credencial}"


def test_sin_encabezado_de_autorizacion_devuelve_401_y_no_delega() -> None:
    llamadas: list[tuple[str, str]] = []
    aplicacion = exigir_autenticacion(_app_interna_espia(llamadas), _SECRETO)

    estado, encabezados, cuerpo = _solicitar(aplicacion)

    assert estado == "401 Unauthorized"
    assert encabezados["WWW-Authenticate"].startswith("Basic")
    assert llamadas == [], "no debe llegar a la aplicacion interna sin autenticar"
    assert _SECRETO not in cuerpo


def test_secreto_correcto_delega_a_la_aplicacion_interna() -> None:
    llamadas: list[tuple[str, str]] = []
    aplicacion = exigir_autenticacion(_app_interna_espia(llamadas), _SECRETO)

    estado, _encabezados, cuerpo = _solicitar(
        aplicacion, autorizacion=_basic("operador", _SECRETO.decode())
    )

    assert estado == "200 OK"
    assert json.loads(cuerpo) == {"ok": True}
    assert llamadas == [("GET", "/panel/x")]


def test_secreto_incorrecto_devuelve_401_y_no_delega() -> None:
    llamadas: list[tuple[str, str]] = []
    aplicacion = exigir_autenticacion(_app_interna_espia(llamadas), _SECRETO)

    estado, _encabezados, _cuerpo = _solicitar(
        aplicacion, autorizacion=_basic("operador", "secreto-incorrecto")
    )

    assert estado == "401 Unauthorized"
    assert llamadas == []


@pytest.mark.parametrize(
    "usuario",
    ["operador", "cualquier-usuario", ""],
)
def test_el_usuario_de_basic_auth_es_ignorado_solo_importa_el_secreto(usuario: str) -> None:
    """Un solo secreto compartido, no una base de usuarios -- el nombre de
    usuario es ruido del diálogo del navegador, no una credencial propia."""
    llamadas: list[tuple[str, str]] = []
    aplicacion = exigir_autenticacion(_app_interna_espia(llamadas), _SECRETO)

    estado, _encabezados, _cuerpo = _solicitar(aplicacion, autorizacion=_basic(usuario, _SECRETO.decode()))

    assert estado == "200 OK"


@pytest.mark.parametrize(
    "autorizacion",
    [
        "",
        "Basic",
        "Basic ",
        "Bearer " + base64.b64encode(b"operador:secreto-sintetico-de-test").decode(),
        "Basic ***no-es-base64-valido***",
        "Basic " + base64.b64encode(b"sin-separador-de-dos-puntos").decode(),
        "Basic " + base64.b64encode(b"").decode(),
    ],
)
def test_encabezados_malformados_o_de_otro_esquema_devuelven_401(autorizacion: str) -> None:
    """Ninguna variante rara de encabezado puede colarse ni tirar una
    excepción no controlada (que WSGI convertiría en 500, filtrando una
    traza) -- todas caen al mismo 401 parejo."""
    llamadas: list[tuple[str, str]] = []
    aplicacion = exigir_autenticacion(_app_interna_espia(llamadas), _SECRETO)

    estado, _encabezados, _cuerpo = _solicitar(aplicacion, autorizacion=autorizacion)

    assert estado == "401 Unauthorized"
    assert llamadas == []


def test_ninguna_ruta_ni_metodo_saltea_la_autenticacion() -> None:
    """La aplicación se envuelve ENTERA -- no hay lista de rutas "públicas"
    que alguien pueda olvidarse de actualizar. Se prueba con una ruta que ni
    siquiera existe en el enrutador real: si esto devolviera 404 en vez de
    401, significaría que la petición SIN AUTENTICAR ya llegó al enrutador
    interno, que es exactamente el salteo que no debe ser posible."""
    llamadas: list[tuple[str, str]] = []
    aplicacion = exigir_autenticacion(_app_interna_espia(llamadas), _SECRETO)

    estado, _encabezados, _cuerpo = _solicitar(aplicacion, ruta="/esta-ruta-no-existe", metodo="POST")

    assert estado == "401 Unauthorized"
    assert llamadas == []


def test_comparacion_del_secreto_usa_hmac_compare_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ataque de temporización: comparar el secreto con `==` filtra cuántos
    bytes iniciales coinciden por cuánto tarda la comparación. Se verifica
    que la comparación pasa por `hmac.compare_digest` (tiempo constante),
    no por una implementación casera."""
    llamadas: list[tuple[bytes, bytes]] = []
    original = hmac.compare_digest

    def _espia(a, b):
        llamadas.append((bytes(a), bytes(b)))
        return original(a, b)

    monkeypatch.setattr("anonimizacion.web.autenticacion_panel.hmac.compare_digest", _espia)

    aplicacion = exigir_autenticacion(_app_interna_espia([]), _SECRETO)
    _solicitar(aplicacion, autorizacion=_basic("operador", _SECRETO.decode()))

    assert len(llamadas) == 1
    assert llamadas[0] == (_SECRETO, _SECRETO)


def test_el_cuerpo_del_401_no_filtra_el_secreto_configurado() -> None:
    aplicacion = exigir_autenticacion(_app_interna_espia([]), _SECRETO)

    _estado, _encabezados, cuerpo = _solicitar(aplicacion)

    assert _SECRETO not in cuerpo
    # el mensaje tiene que ser legible por un no-tecnico, no un JSON crudo
    assert cuerpo.decode("utf-8").strip() != ""
