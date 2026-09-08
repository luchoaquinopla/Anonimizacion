"""Carga del secreto compartido del panel (feature `acceso-al-panel`).

El panel pasó de mostrar sólo lectura a poder lanzar horas de trabajo sobre
cualquier carpeta bajo `--raiz` (`POST /corridas`, feature
`despachador-desde-el-panel`). Este módulo carga el secreto que
`autenticacion_panel.py` exige para cerrar ese hueco.

Deliberadamente SEPARADO de `pseudonimizacion/almacen_pepper.py`, aunque el
patrón sea casi idéntico (dos fuentes con la misma precedencia, mismo
cacheo, mismo "nunca se filtra el valor"): son secretos de naturaleza
distinta que no deben mezclarse ni por accidente de refactor. El pepper HMAC
es el secreto que hace irreversibles las claves de pseudonimización -- si
algún día cambia (rotación, incidente), cualquier `id_paciente` ya generado
se invalida. El secreto del panel es sólo una credencial de acceso a la
interfaz web -- rotarlo no toca un solo dato ya escrito. Compartir el
mismo valor entre los dos acoplaría dos ciclos de vida que no tienen
por qué coincidir (instrucción explícita de la tarea: "el pepper HMAC no
se toca ni se reusa para esto").

Fuentes soportadas, en orden de precedencia (la primera que esté CONFIGURADA
gana -- ver la distinción "configurada" más abajo):

1. Variable de entorno `ANONIMIZACION_PANEL_SECRETO`.
2. Variable de entorno `ANONIMIZACION_PANEL_SECRETO_ARCHIVO` con la ruta a
   un archivo local (mismo uso que `ANONIMIZACION_PEPPER_ARCHIVO`:
   alternativa simple para desarrollo/on-prem; en producción ese archivo
   debe estar cifrado en reposo y con permisos restringidos -- eso es
   responsabilidad de infraestructura, fuera del alcance de este módulo,
   mismo criterio que ya documenta `almacen_pepper.py`).

Si ninguna fuente está CONFIGURADA, `obtener_secreto_panel` lanza
`ErrorSecretoPanelNoConfigurado`. Quien decide qué hacer con esa ausencia es
el punto de entrada (`scripts/servir_panel.py`): con `--escuchar-red` es un
arranque fallido; sirviendo sólo en `127.0.0.1` es tolerado sin
autenticación, para no romper el uso local/de desarrollo que ya existía.

Revisión de seguridad (hallazgos ALTA y MEDIA) -- dos decisiones que valen
la pena dejar explícitas:

1. **"Configurada" no es lo mismo que "no vacía tal cual llegó"**. Las dos
   fuentes se RECORTAN (espacios en blanco al principio/final) ANTES de
   decidir si hay algo ahí. Antes de este cambio sólo la fuente de archivo
   recortaba -- una variable de entorno con un salto de línea colgado (`.env`
   mal generado, o ciertos entornos de Windows que preservan CRLF) cargaba
   un secreto que NUNCA iba a coincidir con lo que el médico tipeaba, sin
   ningún mensaje que lo explicara. Ahora las dos fuentes pasan por el mismo
   `_validar`, así que se comportan igual.
2. **Un valor no vacío es una fuente CONFIGURADA, aunque recorte a algo
   inválido** -- y una fuente configurada con un valor inválido es un error
   FUERTE (`ErrorSecretoPanelInvalido`), nunca un `ErrorSecretoPanelNoConfigurado`
   silencioso. Antes de este cambio, `ANONIMIZACION_PANEL_SECRETO=" "` (un
   solo espacio) pasaba la comprobación de "hay algo acá" tal cual, así que
   `--escuchar-red` arrancaba "protegido" por un secreto que en la práctica
   era adivinable en el primer intento. Ahora ese mismo valor recorta a
   cadena vacía, `_validar` lo rechaza por longitud, y el arranque falla
   fuerte -- exactamente igual que si alguien hubiera tipeado una letra o
   dejado el secreto de un ejemplo de la documentación. La única excepción
   es un archivo COMPLETAMENTE vacío (cero bytes): eso sí se trata como
   fuente ausente, no como fuente inválida -- es indistinguible de "el
   archivo existe pero nadie puso nada todavía", un estado de proyecto
   normal (p. ej. un placeholder en un repo), no una señal de
   misconfiguración activa.

Sobre límite de intentos de autenticación (evaluado, NO implementado -- ver
el "por qué" en el docstring de `autenticacion_panel.py`, sección
correspondiente): este módulo cierra la parte de "el secreto tiene que
tener entropía real"; ese es el control que de verdad importa contra fuerza
bruta en línea. Un limitador de intentos es una capa aparte, con sus propias
contras (estado que un reinicio de un servidor de un solo proceso borra,
bloqueo por IP que puede dejar afuera al médico legítimo) -- no se agrega
acá.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

VAR_ENV_SECRETO = "ANONIMIZACION_PANEL_SECRETO"
VAR_ENV_ARCHIVO_SECRETO = "ANONIMIZACION_PANEL_SECRETO_ARCHIVO"

# Piso de calidad (hallazgo ALTA de la revisión de seguridad): sin esto,
# CUALQUIER string no vacío -- incluido un solo carácter o un espacio --
# pasaba como secreto válido. No se exigen reglas de complejidad
# (mayúsculas/números/símbolos): éste es un panel de un solo operador, sin
# política de rotación ni de usuarios que auditar, así que una regla de
# complejidad sólo agregaría fricción sin cerrar un riesgo real. Lo que sí
# importa es la LONGITUD: 16 caracteres al azar (incluso de un alfabeto
# chico, alfanumérico) ya vuelven inviable adivinar el secreto por fuerza
# bruta en línea en un tiempo práctico -- ver el docstring de
# `autenticacion_panel.py` para por qué esto alcanza sin además necesitar
# un limitador de intentos.
LONGITUD_MINIMA_SECRETO = 16


class ErrorSecretoPanel(RuntimeError):
    """Base común de los errores de configuración del secreto del panel.

    `scripts/servir_panel.py::main` puede capturar esta clase para
    cualquier problema de configuración (no importa cuál exactamente) y
    fallar temprano con el mismo criterio: imprimir el mensaje (nunca
    incluye un valor leído) y salir con código de error, antes de conectar
    a Postgres.
    """


class ErrorSecretoPanelNoConfigurado(ErrorSecretoPanel):
    """Ninguna fuente está configurada -- ni la variable ni el archivo
    tienen contenido alguno.

    Nunca lleva el valor de ninguna variable/archivo leído -- ni en el
    mensaje ni en ningún atributo -- para que no pueda filtrarse por un
    logger que capture la excepción (mismo criterio que
    `ErrorPepperNoConfigurado`).
    """

    def __init__(self) -> None:
        super().__init__(
            f"Secreto del panel no configurado: definir {VAR_ENV_SECRETO} o {VAR_ENV_ARCHIVO_SECRETO}"
        )

    def __repr__(self) -> str:
        return "ErrorSecretoPanelNoConfigurado()"


class ErrorSecretoPanelInvalido(ErrorSecretoPanel):
    """Una fuente SÍ está configurada, pero su valor (ya recortado) no
    alcanza el piso mínimo de calidad (`LONGITUD_MINIMA_SECRETO`).

    Nunca lleva el valor inválido -- ni en el mensaje ni en ningún
    atributo -- por la misma razón que `ErrorSecretoPanelNoConfigurado`: un
    secreto demasiado corto sigue siendo un secreto, y no hay motivo para
    que termine en un log.
    """

    def __init__(self) -> None:
        super().__init__(
            "Secreto del panel invalido: tiene que tener al menos "
            f"{LONGITUD_MINIMA_SECRETO} caracteres despues de recortar espacios en "
            f"blanco -- revisar la fuente configurada ({VAR_ENV_SECRETO} o {VAR_ENV_ARCHIVO_SECRETO})"
        )

    def __repr__(self) -> str:
        return "ErrorSecretoPanelInvalido()"


class ErrorSecretoPanelArchivoIlegible(ErrorSecretoPanel):
    """`ANONIMIZACION_PANEL_SECRETO_ARCHIVO` apunta a una ruta que no se
    pudo leer (no existe, sin permisos, etc.).

    Incluye la RUTA configurada -- no es secreta, ya la conoce quien la
    configuró -- para que se pueda corregir sin leer una traza de Python.
    Lo que nunca incluye es el CONTENIDO del archivo (ni falta que hace: si
    no se pudo leer, no hay contenido que filtrar).
    """

    def __init__(self, ruta: str) -> None:
        self._ruta = ruta
        super().__init__(
            f"No se pudo leer el archivo de {VAR_ENV_ARCHIVO_SECRETO} ({ruta}): "
            "revisar que la ruta exista y sea legible."
        )

    def __repr__(self) -> str:
        return f"ErrorSecretoPanelArchivoIlegible({self._ruta!r})"


def _validar(valor: str) -> bytes:
    """Recorta espacios en blanco y aplica el piso mínimo de longitud.

    Punto ÚNICO de validación para las dos fuentes (revisión de seguridad,
    hallazgo MEDIA de unificación) -- ver el docstring del módulo.
    """
    if len(valor) < LONGITUD_MINIMA_SECRETO:
        raise ErrorSecretoPanelInvalido()
    return valor.encode("utf-8")


@lru_cache(maxsize=1)
def obtener_secreto_panel() -> bytes:
    """Devuelve el secreto cacheado en memoria; lo carga una sola vez.

    En tests, llamar `obtener_secreto_panel.cache_clear()` entre casos para
    que cada uno controle su propio entorno (ver
    `tests/web/test_secreto_panel.py`).
    """
    valor_variable = os.environ.get(VAR_ENV_SECRETO)
    if valor_variable:
        return _validar(valor_variable.strip())

    ruta_archivo = os.environ.get(VAR_ENV_ARCHIVO_SECRETO)
    if ruta_archivo:
        try:
            contenido_crudo = Path(ruta_archivo).read_text(encoding="utf-8")
        except OSError as error:
            # Hallazgo BAJA de la revisión de seguridad: sin este `try`, una
            # ruta mal configurada revienta con un `FileNotFoundError` (u
            # otro `OSError`) crudo que ni `_resolver_secreto_para_arranque`
            # ni `main()` atrapan -- traza de Python en vez de un mensaje
            # claro, justo lo contrario del estándar de "fallar temprano y
            # claro" que el resto de este módulo se propone.
            raise ErrorSecretoPanelArchivoIlegible(ruta_archivo) from error
        if contenido_crudo:
            return _validar(contenido_crudo.strip())

    raise ErrorSecretoPanelNoConfigurado()
