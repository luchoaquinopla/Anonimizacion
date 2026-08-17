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
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import sqlalchemy as sa

from anonimizacion.ingesta.fuente import FuenteArtefacto
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ExitoDocumento, FalloDocumento, ItemLote
from anonimizacion.pseudonimizacion.almacen_pepper import obtener_pepper
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesPostgres
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base

_DB_URL_DEFAULT = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"


def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", required=True, type=Path, help="carpeta con los PDFs a procesar")
    parser.add_argument("--db-url", default=_DB_URL_DEFAULT, help=f"URL de Postgres (default: {_DB_URL_DEFAULT})")
    return parser.parse_args()


def main() -> int:
    args = _parsear_args()

    print(f"Pepper: cargando desde ANONIMIZACION_PEPPER...", file=sys.stderr)
    pepper = obtener_pepper()

    print("Motor de PII: cargando modelo de spaCy (puede tardar unos segundos)...", file=sys.stderr)
    motor = MotorPii()

    print(f"Conectando a Postgres: {args.db_url}", file=sys.stderr)
    engine = sa.create_engine(args.db_url)
    Base.metadata.create_all(engine, checkfirst=True)

    destino = EscritorPostgres(engine)
    cuarentena = EscritorCuarentena(engine)
    # puente id_alt_paciente -> id_paciente persistente contra `vinculo_paciente`
    # (ver docstring del módulo, fix post-merge): sobrevive entre corridas
    # separadas del script, a diferencia de `ResolutorClaves()` en memoria.
    resolutor = ResolutorClavesPostgres(destino)

    ejecutor = EjecutorPipeline(
        resolutor=resolutor,
        motor=motor,
        pepper=pepper,
        destino=destino,
        cuarentena=cuarentena,
    )

    print(f"Listando PDFs en {args.entrada}...", file=sys.stderr)
    artefactos = FuenteArtefacto(args.entrada).listar()
    if not artefactos:
        print("No se encontraron PDFs en esa carpeta.", file=sys.stderr)
        return 1

    items = [ItemLote(id_documento=a.sha256, artefacto=a) for a in artefactos]
    print(f"Procesando {len(items)} documento(s)...", file=sys.stderr)

    resultados = ejecutor.procesar_lote(items)

    exitos = [r for r in resultados if isinstance(r, ExitoDocumento)]
    fallos = [r for r in resultados if isinstance(r, FalloDocumento)]

    print()
    print(f"=== Resultado: {len(exitos)} éxito(s), {len(fallos)} en cuarentena ===")
    print()

    if exitos:
        print("Éxitos:")
        for r in exitos:
            resumen = r.resumen_trazable()
            print(
                f"  - {resumen['id_documento'][:12]}...  tipo={resumen['tipo_documento']:<15}"
                f"  id_paciente={r.id_paciente[:16]}...  id_episodio={r.id_episodio[:16]}..."
            )

    if fallos:
        print()
        print("Cuarentena (motivo -> cantidad):")
        for codigo, cantidad in Counter(r.error.codigo.value for r in fallos).items():
            print(f"  - {codigo}: {cantidad}")
        print()
        print("Detalle por documento:")
        for r in fallos:
            resumen = r.resumen_trazable()
            print(f"  - {resumen['id_documento'][:12]}...  etapa={resumen['etapa']}  codigo={resumen['codigo']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
