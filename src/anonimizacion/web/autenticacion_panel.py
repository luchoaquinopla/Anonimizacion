"""Autenticación mínima del panel: HTTP Basic Auth con secreto compartido, sin base de
usuarios ni estado de sesión (panel de intranet para un solo operador)."""

from __future__ import annotations

import base64
import binascii
import hmac

from .rutas_corridas import AplicacionWsgi, InicioRespuesta

_REALM = "panel-anonimizacion"
_MENSAJE_NO_AUTENTICADO = (
    "No se pudo verificar la identidad para usar el panel. Hace falta el secreto "
    "compartido del panel (variable ANONIMIZACION_PANEL_SECRETO en el servidor) -- "
    "pedilo a quien administra el servidor y volvé a intentar."
).encode("utf-8")


def exigir_autenticacion(aplicacion: AplicacionWsgi, secreto: bytes) -> AplicacionWsgi:
    """Envuelve `aplicacion` exigiendo HTTP Basic Auth contra `secreto` en cada petición,
    sin excepción de ruta ni método -- ninguna ruta nueva puede quedar afuera por olvido."""

    def envoltorio(entorno: dict[str, object], iniciar_respuesta: InicioRespuesta):
        if not _credencial_valida(entorno.get("HTTP_AUTHORIZATION"), secreto):
            return _responder_no_autenticado(iniciar_respuesta)
        return aplicacion(entorno, iniciar_respuesta)

    return envoltorio


def _credencial_valida(encabezado: object, secreto: bytes) -> bool:
    """`True` sólo si el header es `Authorization: Basic ...` válido y la contraseña
    coincide con `secreto` en tiempo constante (`hmac.compare_digest`)."""
    # Cualquier variante malformada devuelve False sin propagar excepción --
    # una excepción sin control acá daría un 500 con traza (filtración).
    if not isinstance(encabezado, str):
        return False
    esquema, _separador, credencial_b64 = encabezado.partition(" ")
    if esquema.lower() != "basic" or not credencial_b64:
        return False
    try:
        decodificado = base64.b64decode(credencial_b64, validate=True)
    except (binascii.Error, ValueError):
        return False
    _usuario, separador_credencial, contrasena = decodificado.partition(b":")
    if not separador_credencial:
        return False
    return hmac.compare_digest(contrasena, secreto)


def _responder_no_autenticado(iniciar_respuesta: InicioRespuesta):
    iniciar_respuesta(
        "401 Unauthorized",
        [
            ("WWW-Authenticate", f'Basic realm="{_REALM}"'),
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(_MENSAJE_NO_AUTENTICADO))),
        ],
    )
    return [_MENSAJE_NO_AUTENTICADO]
