"""Composición del subcomando `anonimizacion servir` (`cli.py` resuelve
banderas/config y llama a `servir()` con argumentos con nombre). Por defecto escucha
sólo en `127.0.0.1`; `--escuchar-red` bindea a todas las interfaces a propósito. Sin
framework: `wsgiref.simple_server` + `ThreadingMixIn` (el `Engine` de SQLAlchemy ya es
seguro entre hilos). Sin secreto configurado, `--escuchar-red` no arranca -- exponer el
panel a toda la red sin autenticación es exactamente el agujero que cierra esa guarda."""

from __future__ import annotations

import socketserver
import sys
from datetime import datetime, timedelta
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

from sqlalchemy import Engine

from anonimizacion.configuracion import _DB_URL_DEFAULT
from anonimizacion.ingesta.lanzador_corrida import (
    MARGEN_INACTIVIDAD_DEFAULT,
    LanzadorCorrida,
    recuperar_corridas_abandonadas,
)
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.pseudonimizacion.almacen_pepper import ErrorPepperNoConfigurado, obtener_pepper
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.web.autenticacion_panel import exigir_autenticacion
from anonimizacion.web.rutas_corridas import AplicacionWsgi, crear_aplicacion_corridas
from anonimizacion.web.secreto_panel import (
    ErrorSecretoPanel,
    ErrorSecretoPanelNoConfigurado,
    obtener_secreto_panel,
)
from anonimizacion.web.servicio_corridas import ServicioCorridasReal

__all__ = ["construir_aplicacion", "servir", "_DB_URL_DEFAULT"]

_PUERTO_DEFAULT = 8000
_HOST_LOCAL = "127.0.0.1"
_HOST_TODAS_LAS_INTERFACES = ""  # equivalente a 0.0.0.0 -- sólo con --escuchar-red
# Tope del apagado cooperativo ante Ctrl+C: tiempo de sobra para que el grupo en vuelo
# termine, sin dejar al operador esperando indefinidamente si algo se cuelga.
_TIMEOUT_APAGADO_SEG = 120


class _ServidorConHilos(socketserver.ThreadingMixIn, WSGIServer):
    """Una conexión por espectador no bloquea a las demás mientras esperan su turno."""

    daemon_threads = True


def construir_aplicacion(
    engine: Engine,
    raiz_autorizada: Path,
    *,
    db_url: str,
    procesos: int,
    secreto: bytes | None = None,
    tope_bytes: int | None = None,
    margen_inactividad: timedelta = MARGEN_INACTIVIDAD_DEFAULT,
    ahora: datetime | None = None,
) -> tuple[AplicacionWsgi, ServicioCorridasReal]:
    """Arma la aplicación WSGI real: `ServicioCorridasReal` sobre `engine`. Devuelve
    `(aplicacion, servicio)`, no sólo `aplicacion`: `servir()` necesita el `servicio`
    para pedirle `solicitar_apagado()`/`esperar_despachos_en_curso()` ante
    `KeyboardInterrupt`. Si `secreto` no es `None`, envuelve toda la app con
    `exigir_autenticacion`. Antes de devolver, cierra como `FALLIDA` toda corrida no
    terminal sin evidencia reciente de trabajo (`recuperar_corridas_abandonadas`)."""
    Base.metadata.create_all(engine, checkfirst=True)
    repositorio = RepositorioCorridas(engine)
    for id_corrida in recuperar_corridas_abandonadas(repositorio, margen_inactividad=margen_inactividad, ahora=ahora):
        print(
            f"Corrida {id_corrida}: recuperada como FALLIDA al arrancar -- quedó abandonada "
            "por un proceso anterior, sin evidencia reciente de trabajo "
            "(ver recuperar_corridas_abandonadas).",
            file=sys.stderr,
        )
    lanzador = LanzadorCorrida(
        repositorio=repositorio,
        cuarentena=EscritorCuarentena(engine),
    )
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=engine, db_url=db_url, procesos=procesos, tope_bytes=tope_bytes
    )
    aplicacion = crear_aplicacion_corridas([raiz_autorizada], servicio, motor_lectura=engine)
    if secreto is not None:
        aplicacion = exigir_autenticacion(aplicacion, secreto)
    return aplicacion, servicio


def _resolver_host(*, escuchar_red: bool) -> str:
    """Sólo `127.0.0.1` salvo pedido explícito. Separada de `servir()` para poder
    fijar la decisión con un test unitario sin levantar ningún servidor real."""
    return _HOST_TODAS_LAS_INTERFACES if escuchar_red else _HOST_LOCAL


def _resolver_secreto_para_arranque(*, escuchar_red: bool) -> bytes | None:
    """Sin fuente configurada: tolera arrancar sin secreto sólo en `127.0.0.1`, nunca
    con `--escuchar-red`. Una fuente configurada pero inválida siempre falla (no se
    captura acá): degradar a "sin autenticación" sería peor que fallar."""
    try:
        return obtener_secreto_panel()
    except ErrorSecretoPanelNoConfigurado:
        if escuchar_red:
            raise
        return None


def servir(*, db_url: str, puerto: int, raiz: Path, procesos: int, escuchar_red: bool) -> int:
    """Composición completa del panel: `cli.py::_comando_servir` ya resolvió
    banderas/config; acá sólo queda pepper, secreto, engine, servidor WSGI."""
    # Verificación de fallo temprano: sin esto, el primer POST /corridas fallaría recién
    # dentro de un proceso hijo, disfrazado de PROCESO_INTERRUMPIDO en cuarentena.
    print("Pepper: verificando ANONIMIZACION_PEPPER/ANONIMIZACION_PEPPER_ARCHIVO...", file=sys.stderr)
    try:
        obtener_pepper()
    except ErrorPepperNoConfigurado as error:
        print(f"No se puede arrancar el panel: {error}", file=sys.stderr)
        return 1

    # Se captura la clase base ErrorSecretoPanel (no sólo NoConfigurado): ningún
    # mensaje incluye un valor leído, así que imprimirlos tal cual no filtra el secreto.
    print(
        "Secreto del panel: verificando ANONIMIZACION_PANEL_SECRETO/ANONIMIZACION_PANEL_SECRETO_ARCHIVO...",
        file=sys.stderr,
    )
    try:
        secreto = _resolver_secreto_para_arranque(escuchar_red=escuchar_red)
    except ErrorSecretoPanel as error:
        print(
            f"No se puede arrancar el panel: {error}",
            file=sys.stderr,
        )
        return 1

    print(f"Conectando a Postgres: {db_url}", file=sys.stderr)
    engine = construir_engine_postgres(db_url)
    aplicacion, servicio = construir_aplicacion(
        engine, raiz, db_url=db_url, procesos=procesos, secreto=secreto
    )

    host = _resolver_host(escuchar_red=escuchar_red)
    servidor = make_server(host, puerto, aplicacion, server_class=_ServidorConHilos)
    if escuchar_red:
        print(
            f"Panel sirviendo en TODA la red en el puerto {puerto} -- "
            "sin autenticación ni TLS (--escuchar-red)",
            file=sys.stderr,
        )
    else:
        print(f"Panel sirviendo en http://127.0.0.1:{puerto}/panel/{{id_corrida}}", file=sys.stderr)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        # Apagado en dos escalones: (1) cooperativo -- deja de tomar grupos nuevos y
        # drena lo en vuelo, pero no interrumpe un worker ya ocupado (medido: el atexit
        # de ProcessPoolExecutor cuelga igual sin esto). (2) forzado -- terminate() a
        # cada worker vivo si el cooperativo se agota; la corrida cierra FALLIDA, honesta
        # sobre que no terminó.
        print(
            "Apagando: si hay una corrida activa, se espera a que termine el grupo en curso "
            f"(hasta {_TIMEOUT_APAGADO_SEG} s) antes de salir.",
            file=sys.stderr,
        )
        servicio.solicitar_apagado()
        servicio.esperar_despachos_en_curso(timeout=_TIMEOUT_APAGADO_SEG)
        if servicio.hay_despachos_en_curso():
            print(
                "El despacho no terminó dentro del tiempo de espera -- terminando los procesos "
                "hijos a la fuerza. El trabajo en vuelo en ese grupo se pierde; la corrida queda "
                "marcada FALLIDA (no completada) para que el próximo arranque no la confunda con "
                "una corrida viva.",
                file=sys.stderr,
            )
            servicio.terminar_despachos_a_la_fuerza()
    finally:
        servidor.server_close()
    return 0
