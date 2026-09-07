"""Script de prueba manual: procesa una carpeta de PDFs con el pipeline real.

Uso:
    export ANONIMIZACION_PEPPER="pepper-de-prueba-cambiar-en-produccion"
    python scripts/procesar_carpeta.py --entrada ./mis_pdfs

Requiere Postgres corriendo (ver docker-compose.yml, puerto 5433 por
defecto) y la variable ANONIMIZACION_PEPPER seteada (ver
`pseudonimizacion/almacen_pepper.py`).

Simplificaciones deliberadas de este script (no del pipeline en si):
- Crea el esquema con `Base.metadata.create_all` en vez de correr las
  migraciones de Alembic -- valido para probar rapido, no para produccion
  (ahi corresponde `alembic upgrade head`, ver migrations/).
- Solo escribe a Postgres, no exporta a Parquet en el mismo paso (serian
  dos destinos distintos; EjecutorPipeline hoy toma uno solo -- exportar a
  Parquet despues es una consulta aparte contra lo ya escrito en Postgres).

Fix post-merge (ver `sdd/pdf-pii-anonymization/apply-progress`, seccion
"Fix: persistencia del puente id_alt_paciente en Postgres entre corridas"):
este script usaba `ResolutorClaves()` (puente en memoria, vacio en cada
corrida) -- el laboratorio de un paciente subido en una corrida y el ECG del
mismo paciente subido en OTRA corrida posterior nunca se vinculaban, aunque
el laboratorio ya estuviera en la base. Ahora usa `ResolutorClavesPostgres`
(`pseudonimizacion/resolutor_claves.py`), que delega contra la tabla real
`vinculo_paciente` via `EscritorPostgres` -- el puente persiste entre
corridas separadas del script, no solo dentro de un mismo lote.

Fix `panel-de-operacion` (tasks.md 6.8-6.9, PR 2.5): este script armaba
`FuenteLocal`/`ItemLote` a mano y llamaba `EjecutorPipeline.procesar_lote(items)`
directo, sin ningun `corrida_id` -- ni la corrida ni el inventario quedaban
registrados en ningun lado. Ahora usa `LanzadorCorrida` (crea la `Corrida`,
inventaria via `RepositorioCorridas.registrar_documentos`) y
`trabajadores.tareas.procesar_grupo` -- la MISMA tarea Celery que despachara
produccion, llamada en directo (no `.delay()`: este script corre sincronico,
sin broker, y llamar la tarea como funcion ejercita exactamente el mismo
codigo que corre en el worker) -- para que `corrida_id` viaje hasta
`estudio`/`cuarentena` (design.md, "Recorrido"). Es tambien el primer
llamador de produccion real de `LanzadorCorrida`/`CuarentenaDeCorrida`
(Fase 6.4-6.7): sin este cambio quedaban con tests pero sin ningun camino
que los ejecutara fuera de la suite.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import Engine

from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pseudonimizacion.almacen_pepper import obtener_pepper
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesPostgres
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres, construir_engine_postgres
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.trabajadores import tareas

_DB_URL_DEFAULT = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"


def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", required=True, type=Path, help="carpeta con los PDFs a procesar")
    parser.add_argument("--db-url", default=_DB_URL_DEFAULT, help=f"URL de Postgres (default: {_DB_URL_DEFAULT})")
    return parser.parse_args()


def ejecutar(
    *,
    entrada: Path,
    engine: Engine,
    motor: MotorPii,
    pepper: bytes,
    tope_bytes: int | None = None,
) -> int:
    """Lanza una corrida sobre `entrada` y procesa su inventario de punta a punta.

    Separado de `main()` para poder ejercitarlo con un motor/engine inyectados
    en tests (`tests/scripts/test_procesar_carpeta.py`) sin tocar argparse,
    variables de entorno, ni Postgres real. `tope_bytes=None` es "usar el
    default de producción" -- mismo convenio que `LanzadorCorrida`/`FuenteLocal`.
    """
    Base.metadata.create_all(engine, checkfirst=True)

    destino = EscritorPostgres(engine)
    cuarentena = EscritorCuarentena(engine)
    # puente id_alt_paciente -> id_paciente persistente contra `vinculo_paciente`
    # (ver docstring del módulo, fix post-merge): sobrevive entre corridas
    # separadas del script, a diferencia de `ResolutorClaves()` en memoria.
    resolutor = ResolutorClavesPostgres(destino)

    # Se arma por la MISMA raíz de composición que el trabajador
    # (`construir_fabrica_ejecutor`) y no a mano: armarlo por separado fue lo que
    # dejó a este script sin validación de episodio mientras el banco de carga sí
    # la tenía. Con la fábrica, el script valida igual que producción
    # (spec `procesamiento-por-grupo`, requisito 6).
    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(entrada,),
        resolutor=resolutor,
        motor=motor,
        pepper=pepper,
        destino=destino,
        cuarentena=cuarentena,
        **({"tope_bytes": tope_bytes} if tope_bytes is not None else {}),
    )
    tareas.configurar_ejecutor(fabrica)

    # `LanzadorCorrida` es el único punto donde nace una corrida (design.md,
    # "Recorrido"): crea la fila `corrida`, inventaría vía `FuenteLocal` +
    # `RepositorioCorridas.registrar_documentos`, y devuelve las referencias
    # ya en la forma exacta que exige `procesar_grupo`. Un artefacto apartado
    # por sobretamaño (antes de calcular su huella, así que nunca llega al
    # inventario) igual queda atribuido a esta corrida vía `CuarentenaDeCorrida`,
    # que `LanzadorCorrida` arma internamente.
    lanzador = LanzadorCorrida(
        repositorio=RepositorioCorridas(engine),
        cuarentena=cuarentena,
        **({"tope_bytes": tope_bytes} if tope_bytes is not None else {}),
    )
    print(f"Lanzando corrida sobre {entrada}...", file=sys.stderr)
    lanzamiento = lanzador.lanzar(entrada)

    if not lanzamiento.referencias:
        print("No se encontraron PDFs en esa carpeta.", file=sys.stderr)
        return 1

    # `lanzador.lanzar()` sólo inventaría -- no avanza a PROCESANDO (cierre de
    # silencio de auditoría, `fix/silencios-de-ingesta-y-panel`): inventariar
    # y procesar son cosas distintas, y quien sólo inventaría no puede
    # afirmar que está procesando. Este script es quien REALMENTE va a llamar
    # `procesar_grupo` a continuación, así que es quien debe marcarlo.
    lanzador.marcar_procesando(lanzamiento.corrida_id)

    print(
        f"Corrida {lanzamiento.corrida_id}: procesando {len(lanzamiento.referencias)} documento(s)...",
        file=sys.stderr,
    )
    # `procesar_grupo` es la MISMA tarea Celery real que despachara producción
    # (llamada en directo, no `.delay()`: este script corre sincrónico, sin
    # broker) -- el único llamador que hace real `corrida_id` de punta a punta
    # hasta `estudio`/`cuarentena`.
    resultados = tareas.procesar_grupo(lanzamiento.corrida_id, lanzamiento.referencias)

    exitos = [r for r in resultados if r["estado"] == "exito"]
    fallos = [r for r in resultados if r["estado"] != "exito"]

    print()
    print(f"=== Corrida {lanzamiento.corrida_id}: {len(exitos)} éxito(s), {len(fallos)} en cuarentena ===")
    print()

    if exitos:
        print("Éxitos:")
        for r in exitos:
            print(f"  - {r['id_documento'][:12]}...  tipo={r['tipo_documento']:<15}")

    if fallos:
        print()
        print("Cuarentena (motivo -> cantidad):")
        for codigo, cantidad in Counter(r["codigo"] for r in fallos).items():
            print(f"  - {codigo}: {cantidad}")
        print()
        print("Detalle por documento:")
        for r in fallos:
            print(f"  - {r['id_documento'][:12]}...  etapa={r['etapa']}  codigo={r['codigo']}")

    return 0


def main() -> int:
    args = _parsear_args()

    print("Pepper: cargando desde ANONIMIZACION_PEPPER...", file=sys.stderr)
    pepper = obtener_pepper()

    print("Motor de PII: cargando modelo de spaCy (puede tardar unos segundos)...", file=sys.stderr)
    motor = MotorPii()

    print(f"Conectando a Postgres: {args.db_url}", file=sys.stderr)
    # `construir_engine_postgres` (openspec `paralelismo-de-procesamiento` PR 1)
    # arma el pool con `pool_pre_ping`/`pool_recycle` contra RDS -- ver el
    # docstring de esa función para el porqué un `sa.create_engine(url)` pelado
    # manda documentos válidos a cuarentena por una conexión muerta del pool.
    engine = construir_engine_postgres(args.db_url)

    return ejecutar(entrada=args.entrada, engine=engine, motor=motor, pepper=pepper)


if __name__ == "__main__":
    raise SystemExit(main())
