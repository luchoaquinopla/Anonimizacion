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
"""

from __future__ import annotations

import argparse
import socketserver
import sys
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

import sqlalchemy as sa
from sqlalchemy import Engine

from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.web.rutas_corridas import crear_aplicacion_corridas
from anonimizacion.web.servicio_corridas import ServicioCorridasReal

_DB_URL_DEFAULT = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"
_PUERTO_DEFAULT = 8000
_HOST_LOCAL = "127.0.0.1"
_HOST_TODAS_LAS_INTERFACES = ""  # equivalente a 0.0.0.0 -- sólo con --escuchar-red


class _ServidorConHilos(socketserver.ThreadingMixIn, WSGIServer):
    """`WSGIServer` + `ThreadingMixIn`: una conexión por espectador no bloquea
    a las demás mientras esperan su turno de consulta (design.md, "El punto
    de entrada")."""

    daemon_threads = True


def construir_aplicacion(engine: Engine, raiz_autorizada: Path):
    """Arma la aplicación WSGI real: `ServicioCorridasReal` sobre `engine`.

    Separado de `main()` para poder ejercitarlo en tests
    (`tests/scripts/test_servir_panel.py`) sin pasar por argparse ni por
    Postgres real -- mismo patrón que `scripts/procesar_carpeta.py::ejecutar`.
    """
    Base.metadata.create_all(engine, checkfirst=True)
    lanzador = LanzadorCorrida(
        repositorio=RepositorioCorridas(engine),
        cuarentena=EscritorCuarentena(engine),
    )
    servicio = ServicioCorridasReal(lanzador=lanzador, motor=engine)
    return crear_aplicacion_corridas([raiz_autorizada], servicio, motor_lectura=engine)


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
    print(f"Conectando a Postgres: {args.db_url}", file=sys.stderr)
    engine = sa.create_engine(args.db_url)
    aplicacion = construir_aplicacion(engine, args.raiz)

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
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
