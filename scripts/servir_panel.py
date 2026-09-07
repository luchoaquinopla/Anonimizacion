"""Punto de entrada WSGI del panel de operación (design.md, "El punto de entrada").

Uso:
    python scripts/servir_panel.py --db-url postgresql+psycopg://... --puerto 8000 --raiz ./mis_pdfs

Por defecto escucha SÓLO en `127.0.0.1` -- no en todas las interfaces. Este
panel muestra datos operativos de una corrida clínica sin autenticación y
sin TLS (design.md, "El punto de entrada": documentado como suficiente para
la intranet del instituto, pero un default documentado sigue siendo un
default: quien levanta el servidor escribe el comando, no lee el diseño).
Para exponerlo al resto de la red hace falta pedirlo a propósito con
`--escuchar-red`, que bindea a todas las interfaces (`""`, equivalente a
`0.0.0.0`) -- así quien comparte el panel sabe que lo está haciendo, y quien
sólo quiere mirarlo en su máquina no expone nada sin enterarse.

Sin framework, cero dependencias nuevas (design.md, Decisión 10):
`wsgiref.simple_server` con `socketserver.ThreadingMixIn` -- cinco líneas de
stdlib. `wsgiref` sin hilos serializa las solicitudes; con varios
espectadores refrescando el panel cada 1-2 s, una consulta lenta bloquearía
a todos los demás mientras esperan su turno. El `Engine` de SQLAlchemy es
seguro entre hilos -- cada uno toma su propia conexión del pool -- así que
agregar hilos acá no introduce ningún estado compartido nuevo.

Documentado como suficiente para la intranet del instituto: sin
autenticación, sin TLS. Si aparece necesidad real de concurrencia o de
exponerlo fuera de la intranet, gunicorn adelante sin tocar la aplicación.

Feature `despachador-desde-el-panel`: `POST /corridas` ya no sólo inventaría
-- despacha el inventario de verdad, en un hilo de fondo, con
`anonimizacion.trabajadores.despacho_paralelo.despachar_en_paralelo` (ver
`web/servicio_corridas.py`). Esta misma condición de "el `Engine` de
SQLAlchemy es seguro entre hilos" es la que permite que ESE hilo de fondo
comparta el mismo `Engine` que atiende al resto del panel sin agregar ningún
lock nuevo -- ya era cierto para `_ServidorConHilos`, y se sigue cumpliendo.

Este punto de entrada agrega, para esa misma feature:

- `--procesos`: grado de concurrencia de CADA corrida despachada (mismo
  significado y mismo default que `scripts/procesar_carpeta.py --procesos`).
- Verificación temprana del pepper (`ANONIMIZACION_PEPPER`): sin él, cada
  proceso hijo fallaría recién al arrancar
  (`despacho_paralelo.inicializar_trabajador`), a mitad de una corrida ya
  aceptada, disfrazado de `PROCESO_INTERRUMPIDO` en cuarentena -- `main()`
  lo verifica ANTES de conectar a Postgres o de aceptar ningún `POST /corridas`.
- Recuperación de arranque (`lanzador_corrida.recuperar_corridas_abandonadas`):
  toda corrida no terminal al construir la aplicación es necesariamente una
  corrida abandonada por un proceso anterior -- este servidor es de un solo
  proceso, sin persistencia de "hay un hilo corriendo para este `corrida_id`"
  a través de un reinicio. Sin esto, el gate de "una corrida a la vez"
  quedaría bloqueado para siempre tras cualquier caída.

Dos corridas simultáneas: rechazadas (`409`, `ServicioCorridasReal.crear_corrida`)
-- este panel es para UN operador, y `despachar_en_paralelo` ya reserva su
propio presupuesto de memoria por corrida (~875 MB por proceso de `MotorPii`).

Seguridad (feature `despachador-desde-el-panel`): antes de este cambio, un
panel sin autenticación en `127.0.0.1` sólo exponía LECTURA de datos
operativos. Ahora `POST /corridas`/`POST /corridas/{id}/reintentar` pueden
lanzar trabajo pesado (horas de CPU, procesos hijos con el pepper heredado).
Sigue sin autenticación (fuera de alcance de este cambio, ver el mensaje de
la tarea) -- pero el default sigue siendo `127.0.0.1` y `--escuchar-red`
sigue siendo un pedido explícito; con este cambio, olvidarse de pedirlo a
propósito ya no sólo evita exponer LECTURAS, evita que cualquiera en la red
del instituto pueda lanzar una corrida de horas sobre CUALQUIER ruta bajo
`--raiz` sin ningún control de quién la pidió.
"""

from __future__ import annotations

import argparse
import socketserver
import sys
from datetime import datetime, timedelta
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

from sqlalchemy import Engine

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
from anonimizacion.trabajadores import despacho_paralelo
from anonimizacion.web.rutas_corridas import AplicacionWsgi, crear_aplicacion_corridas
from anonimizacion.web.servicio_corridas import ServicioCorridasReal

_DB_URL_DEFAULT = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
_PUERTO_DEFAULT = 8000
_HOST_LOCAL = "127.0.0.1"
_HOST_TODAS_LAS_INTERFACES = ""  # equivalente a 0.0.0.0 -- sólo con --escuchar-red
# Tope del apagado cooperativo ante Ctrl+C (revisión adversarial crítico 2):
# tiempo de sobra para que el grupo EN VUELO en cada corrida activa termine
# (segundos a bajas decenas de segundos por grupo, ver `despacho_paralelo.py`)
# sin dejar al operador esperando indefinidamente si algo se cuelga de verdad.
_TIMEOUT_APAGADO_SEG = 120


def _tipo_procesos(valor: str) -> int:
    """`type=` de argparse para `--procesos`: mismo patrón que
    `scripts/procesar_carpeta.py::_tipo_procesos` -- valida contra el tope
    duro ACÁ, no en `construir_aplicacion`, para que un valor inválido falle
    con un mensaje de `argparse` claro antes de tocar Postgres."""
    return despacho_paralelo.validar_grado_concurrencia(int(valor))


class _ServidorConHilos(socketserver.ThreadingMixIn, WSGIServer):
    """`WSGIServer` + `ThreadingMixIn`: una conexión por espectador no bloquea
    a las demás mientras esperan su turno de consulta (design.md, "El punto
    de entrada")."""

    daemon_threads = True


def construir_aplicacion(
    engine: Engine,
    raiz_autorizada: Path,
    *,
    db_url: str,
    procesos: int,
    tope_bytes: int | None = None,
    margen_inactividad: timedelta = MARGEN_INACTIVIDAD_DEFAULT,
    ahora: datetime | None = None,
) -> tuple[AplicacionWsgi, ServicioCorridasReal]:
    """Arma la aplicación WSGI real: `ServicioCorridasReal` sobre `engine`.

    Separado de `main()` para poder ejercitarlo en tests
    (`tests/scripts/test_servir_panel.py`) sin pasar por argparse ni por
    Postgres real -- mismo patrón que `scripts/procesar_carpeta.py::ejecutar`.

    Devuelve `(aplicacion, servicio)`, no sólo `aplicacion` (revisión
    adversarial crítico 2): `main()` necesita el `servicio` para poder
    pedirle `solicitar_apagado()`/`esperar_despachos_en_curso()` ante
    `KeyboardInterrupt` -- devolver sólo la app WSGI dejaba a `main()` sin
    forma de alcanzar los hilos de despacho que lanzó.

    `db_url`/`procesos` viajan hasta `ServicioCorridasReal`: cada corrida
    despachada arma su propio `ProcessPoolExecutor` (`db_url` porque cada
    proceso hijo arma su PROPIO `Engine` -- una conexión de socket no
    sobrevive un pickle a través del límite de proceso) con ese grado de
    concurrencia (feature `despachador-desde-el-panel`).

    Recuperación de arranque (decisión "qué pasa si el servidor se cae con
    una corrida en curso"): ANTES de devolver la aplicación, cierra como
    `FALLIDA` toda corrida no terminal SIN evidencia reciente de trabajo --
    ver `lanzador_corrida.recuperar_corridas_abandonadas` (revisión
    adversarial crítico 1: la versión anterior asumía que CUALQUIER corrida
    no terminal estaba abandonada, lo cual es falso mientras
    `scripts/procesar_carpeta.py` siga corriendo contra la misma base).
    `margen_inactividad`/`ahora` son un passthrough para tests (mismo patrón
    que `reloj` en `embudo_corrida.construir_embudo`); producción usa el
    default y el reloj real.
    """
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
    return aplicacion, servicio


def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=_DB_URL_DEFAULT, help=f"URL de Postgres (default: {_DB_URL_DEFAULT})")
    parser.add_argument("--puerto", type=int, default=_PUERTO_DEFAULT)
    parser.add_argument(
        "--raiz",
        type=Path,
        default=Path("."),
        help="raíz autorizada para lanzar corridas nuevas vía POST /corridas",
    )
    parser.add_argument(
        "--procesos",
        type=_tipo_procesos,
        default=despacho_paralelo.grado_de_concurrencia_por_defecto(),
        help=(
            "grado de concurrencia de CADA corrida despachada desde el panel "
            "(ProcessPoolExecutor); mismo default y mismo tope duro que "
            "scripts/procesar_carpeta.py --procesos"
        ),
    )
    parser.add_argument(
        "--escuchar-red",
        action="store_true",
        help=(
            "expone el panel a toda la red del instituto (bindea a todas las interfaces) "
            "en vez de sólo a 127.0.0.1. Sin autenticación ni TLS -- pedirlo a propósito."
        ),
    )
    return parser.parse_args()


def _resolver_host(*, escuchar_red: bool) -> str:
    """Sólo `127.0.0.1` salvo pedido explícito -- ver el docstring del módulo.

    Separada de `main()` para poder fijar la decisión con un test unitario
    sin levantar ningún servidor real.
    """
    return _HOST_TODAS_LAS_INTERFACES if escuchar_red else _HOST_LOCAL


def main() -> int:
    args = _parsear_args()

    # Decisión "el pepper HMAC" (feature `despachador-desde-el-panel`): se
    # verifica ACÁ, antes de tocar Postgres, y no se guarda el valor en
    # ningún lado -- cada proceso hijo lo vuelve a leer de su propio entorno
    # heredado (`despacho_paralelo.inicializar_trabajador`). Esto es SÓLO una
    # comprobación de fallo temprano: sin ella, el primer `POST /corridas`
    # fallaría recién dentro de un proceso hijo, a mitad de una corrida ya
    # aceptada, y quedaría disfrazado de `PROCESO_INTERRUMPIDO` en cuarentena
    # en vez de señalar la causa real (una variable de entorno faltante en
    # el SERVIDOR).
    print("Pepper: verificando ANONIMIZACION_PEPPER/ANONIMIZACION_PEPPER_ARCHIVO...", file=sys.stderr)
    try:
        obtener_pepper()
    except ErrorPepperNoConfigurado as error:
        print(f"No se puede arrancar el panel: {error}", file=sys.stderr)
        return 1

    print(f"Conectando a Postgres: {args.db_url}", file=sys.stderr)
    # `construir_engine_postgres` (openspec `paralelismo-de-procesamiento` PR 1)
    # arma el pool con `pool_pre_ping`/`pool_recycle` contra RDS -- este panel
    # es un proceso de larga vida, exactamente el perfil que una conexión
    # muerta del pool afecta (ver docstring de esa función).
    engine = construir_engine_postgres(args.db_url)
    aplicacion, servicio = construir_aplicacion(engine, args.raiz, db_url=args.db_url, procesos=args.procesos)

    host = _resolver_host(escuchar_red=args.escuchar_red)
    servidor = make_server(host, args.puerto, aplicacion, server_class=_ServidorConHilos)
    if args.escuchar_red:
        print(
            f"Panel sirviendo en TODA la red en el puerto {args.puerto} -- "
            "sin autenticación ni TLS (--escuchar-red)",
            file=sys.stderr,
        )
    else:
        print(f"Panel sirviendo en http://127.0.0.1:{args.puerto}/panel/{{id_corrida}}", file=sys.stderr)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        # Decisión "Ctrl+C a mitad de una corrida" (revisión adversarial
        # crítico 2, corregida en ronda 3, hallazgo 3): apagado en DOS
        # escalones.
        #
        # (1) COOPERATIVO: `solicitar_apagado()` hace que cada despacho en
        # curso deje de tomar grupos NUEVOS
        # (`despacho_paralelo.despachar_en_paralelo`, parámetro `detener`) y
        # drene lo que ya estaba en vuelo. Acota el apagado al tiempo de
        # ESOS grupos (segundos a bajas decenas de segundos) mientras nada
        # esté ya trabado -- pero NO interrumpe un worker que ya está
        # ocupado: medido, con el cooperativo agotado, el proceso quedaba
        # colgado igual (~114 s con un timeout de 0,2 s) porque
        # `ProcessPoolExecutor` registra su propio `atexit` que espera al
        # pool ACTIVO sin importar `daemon=True`.
        #
        # (2) FORZADO: si el cooperativo se agota, `terminar_despachos_a_la_fuerza()`
        # manda `.terminate()` a cada worker vivo. El trabajo en vuelo en
        # ESE momento se pierde -- ningún documento a medio procesar llega a
        # escribirse -- pero `_despachar_y_cerrar` ya cierra esa corrida
        # `FALLIDA` (nunca `COMPLETADA`) cuando `detener` está seteado: la
        # base queda honesta sobre que no terminó, no silenciosamente
        # colgada ni mintiendo un desenlace que nunca ocurrió.
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


if __name__ == "__main__":
    raise SystemExit(main())
