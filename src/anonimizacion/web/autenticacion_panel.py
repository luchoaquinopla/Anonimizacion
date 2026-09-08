"""Autenticación mínima del panel: secreto compartido vía HTTP Basic Auth
(feature `acceso-al-panel`).

Por qué esto y no otra cosa (decisión de la tarea, evaluada explícitamente):

- **Usuario/contraseña persistidos**: se descartó. Agrega una base de
  usuarios, altas, hashes, recuperación de contraseña -- superficie
  desproporcionada para un panel de UN operador. Además hubiera exigido una
  migración Alembic nueva sólo para guardar credenciales de sesión, cuando
  el resto del cambio no necesita tocar la base en absoluto.
- **Un secreto compartido detrás de un formulario de login a medida**: se
  descartó frente a Basic Auth. Un formulario propio es más código (HTML,
  manejo de sesión/cookie, y ese formulario en sí sería una superficie
  nueva) para cerrar exactamente el mismo riesgo que ya cierra un mecanismo
  que el navegador ya implementa de forma nativa y sin JavaScript.
- **HTTP Basic Auth con un secreto compartido** (elegido): el navegador
  muestra el diálogo nativo de credenciales -- ningún médico necesita que le
  expliquen una pantalla de login nueva. Sin base de usuarios: un solo
  secreto (`secreto_panel.obtener_secreto_panel`), sin altas ni
  recuperación. Sin estado de sesión (ni cookies, ni tokens que
  gestionar): cada petición se valida contra el mismo secreto, así que no
  hay nada que expire de forma sorpresiva ni que limpiar al cerrar el
  servidor. Reemplazable después por el mecanismo institucional: es un
  esquema HTTP estándar (`WWW-Authenticate: Basic`), el mismo que un proxy
  reverso con LDAP/SSO institucional puede terminar por su cuenta sin tocar
  esta aplicación -- ver `exigir_autenticacion` más abajo, que envuelve
  cualquier aplicación WSGI y puede reemplazarse entera por otra que hable
  el protocolo del instituto sin tocar `rutas_corridas.py`.

Qué NO resuelve (documentado, no escondido):

- **TLS queda fuera de alcance de este cambio** (mismo alcance que ya
  documenta `scripts/servir_panel.py`: "suficiente para la intranet del
  instituto"). Sin TLS, Basic Auth viaja en Base64 -- NO cifrado, trivial de
  decodificar -- así que cualquiera que pueda observar tráfico en el mismo
  segmento de red ve el secreto en texto plano y puede reusarlo hasta que se
  rote a mano (el secreto no expira solo). Aceptable sólo si el segmento de
  red entre el navegador del médico y el host del panel es un segmento
  conmutado que el IT del instituto ya trata como confiable, y
  `--escuchar-red` no se usa fuera de ese segmento (nunca sobre VPN ni
  infraestructura expuesta). El día que se integre el mecanismo de
  identidad del instituto, TLS debería llegar con él (típicamente vía el
  proxy reverso que ya termina esa autenticación).
- `hmac.compare_digest` no oculta la LONGITUD del secreto que se está
  comparando (limitación documentada de la propia función) -- sólo evita
  filtrar cuántos bytes iniciales coinciden. No es un problema práctico acá:
  quien configura el secreto controla su longitud, y adivinar su longitud
  exacta no acerca a nadie a adivinar su contenido.

Qué se protege: TODO el panel, no sólo `POST /corridas`. `exigir_autenticacion`
envuelve la aplicación WSGI COMPLETA en `scripts/servir_panel.py`, antes de
que cualquier petición llegue al enrutador de `rutas_corridas.py` -- ninguna
ruta, ni una nueva que se agregue mañana, puede quedar afuera por olvido
(no hay una lista de "rutas públicas" que mantener sincronizada). Una
petición sin autenticar recibe el mismo 401 exista o no la ruta pedida: así
tampoco se puede usar el panel para enumerar qué rutas existen antes de
autenticarse.

Sobre CSRF con Basic Auth (considerado, no un hueco nuevo): un navegador
reenvía credenciales de Basic Auth cacheadas a CUALQUIER pestaña que pida el
mismo origen, así que en teoría una página maliciosa abierta en otra
pestaña podría intentar disparar una acción de escritura. Dos barreras ya
existentes en `rutas_corridas.py` lo evitan en LAS DOS rutas de escritura
(`POST /corridas` y `POST /corridas/{id}/reintentar` -- revisión de
seguridad, hallazgo MEDIA: la primera versión de este cambio sólo verificó
la primera; la segunda quedó sin el mismo chequeo hasta que se agregó
explícitamente, ver `_reintentar_corrida` en `rutas_corridas.py`): (1) las
dos exigen `Content-Type: application/json` exacto (415 si no), y un
`<form>` HTML sólo puede mandar
`application/x-www-form-urlencoded`/`multipart/form-data`/`text/plain` --
nunca JSON sin JavaScript; (2) un `fetch()` cross-origin con
`Content-Type: application/json` deja de ser una petición "simple" y exige
preflight CORS -- este servidor no emite ningún encabezado
`Access-Control-Allow-Origin`, así que el navegador bloquea el preflight y
la petición real nunca sale. No se agrega ningún encabezado CORS a
propósito: agregarlo sería DEBILITAR esta barrera, no reforzarla. Cualquier
ruta de escritura NUEVA que se agregue después tiene que repetir el mismo
chequeo de `Content-Type` -- no es automático por estar detrás de
`exigir_autenticacion`, que sólo verifica IDENTIDAD, no protege por sí solo
contra CSRF.

Sobre límite de intentos de autenticación (evaluado, NO implementado --
revisión de seguridad, hallazgo ALTA): se consideró un contador en memoria
que bloquee tras N intentos fallidos, y se decidió NO agregarlo, por estas
razones:

1. **El control que de verdad cierra fuerza bruta ya está en
   `secreto_panel.py`**: el piso mínimo de longitud
   (`LONGITUD_MINIMA_SECRETO = 16`) hace que adivinar el secreto en línea,
   un intento HTTP a la vez, sea inviable en un tiempo práctico incluso SIN
   ningún límite de intentos -- un espacio de búsqueda de ese tamaño no se
   agota probando online, con o sin demora entre intentos.
2. **El riesgo real no es "alguien adivina el secreto probando"**, es
   "alguien lo CAPTURA" -- la ausencia de TLS (ver más arriba) significa
   que el secreto viaja en claro por la red si alguien observa tráfico. Un
   límite de intentos no hace NADA contra un atacante que ya tiene el
   secreto correcto: lo usa una sola vez y entra. Agregar un contador
   habría gastado código y complejidad en el vector que YA está cerrado
   (fuerza bruta online) sin tocar el vector que sigue abierto (captura de
   tráfico).
3. **Un contador en memoria, en ESTE servidor (un solo proceso,
   `wsgiref.simple_server`), tiene sus propias trampas**: un reinicio lo
   borra por completo -- y este panel YA se reinicia solo tras cualquier
   caída (`recuperar_corridas_abandonadas` en `scripts/servir_panel.py`),
   así que un atacante con paciencia para forzar o esperar un reinicio
   recupera el contador en cero gratis. Bloquear por IP es peor todavía
   para el caso de uso real: un panel de intranet para UN operador, donde
   una IP mal escrita cinco veces bloquea exactamente a la persona
   legítima que lo necesita usar, sin ningún camino de auto-recuperación
   más allá de pedirle a alguien que reinicie el servidor -- que es
   exactamente la clase de fricción operativa que este cambio evitó a
   propósito al no construir un formulario de login con estado.

Si el mecanismo de autenticación institucional reemplaza esto en el futuro
(ver más arriba), es esperable que SÍ traiga su propio límite de intentos
del lado del servidor de identidad -- ese es el lugar correcto para esa
lógica, no un panel de un solo proceso sin persistencia de sesión.
"""

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
    """Envuelve `aplicacion` (cualquier callable WSGI) exigiendo HTTP Basic
    Auth contra `secreto` en CADA petición, sin excepción de ruta ni método.

    No hay estado de sesión: no se emite cookie ni token propio. El
    navegador es quien cachea las credenciales una vez que el usuario las
    tipeó en su diálogo nativo -- este envoltorio nunca necesita saber que
    ya autenticó antes.
    """

    def envoltorio(entorno: dict[str, object], iniciar_respuesta: InicioRespuesta):
        if not _credencial_valida(entorno.get("HTTP_AUTHORIZATION"), secreto):
            return _responder_no_autenticado(iniciar_respuesta)
        return aplicacion(entorno, iniciar_respuesta)

    return envoltorio


def _credencial_valida(encabezado: object, secreto: bytes) -> bool:
    """`True` sólo si `encabezado` es un `Authorization: Basic ...` válido
    cuya CONTRASEÑA (no el usuario -- ver el docstring del módulo) coincide
    con `secreto`, comparado en tiempo constante (`hmac.compare_digest`)
    para no filtrar por temporización cuántos bytes iniciales coinciden.

    Cualquier variante malformada (esquema distinto, base64 inválido, sin
    separador `:`) devuelve `False` sin propagar ninguna excepción -- WSGI
    convertiría una excepción no controlada acá en un 500 con traza, que es
    exactamente la clase de filtración que esta función tiene que evitar.
    """
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
