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
import itertools
import sys
from collections import Counter
from collections.abc import Iterator
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
from anonimizacion.trabajadores import despacho_paralelo, tareas

_DB_URL_DEFAULT = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"


def _tipo_procesos(valor: str) -> int:
    """`type=` de argparse para `--procesos`: valida contra el tope duro acá
    (no en `ejecutar()`) para que un valor inválido falle con un mensaje de
    `argparse` claro antes de tocar Postgres/spaCy, no a mitad de una corrida."""
    return despacho_paralelo.validar_grado_concurrencia(int(valor))


def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", required=True, type=Path, help="carpeta con los PDFs a procesar")
    parser.add_argument("--db-url", default=_DB_URL_DEFAULT, help=f"URL de Postgres (default: {_DB_URL_DEFAULT})")
    parser.add_argument(
        "--procesos",
        type=_tipo_procesos,
        default=despacho_paralelo.grado_de_concurrencia_por_defecto(),
        help=(
            "grado de concurrencia (ProcessPoolExecutor); default conservador segun "
            "nucleos logicos y memoria medida (ver anonimizacion.trabajadores."
            "despacho_paralelo.grado_de_concurrencia_por_defecto), tope duro 2x nucleos"
        ),
    )
    return parser.parse_args()


def _configurar_ejecutor_secuencial(
    *,
    entrada: Path,
    motor: MotorPii | None,
    pepper: bytes,
    destino: EscritorPostgres,
    cuarentena: EscritorCuarentena,
    tope_bytes: int | None,
) -> None:
    """Arma y registra la fábrica de `EjecutorPipeline` en ESTE proceso --
    solo para el camino secuencial (`procesos<=1`). Extraído de `ejecutar()`
    para mantener su complejidad ciclomática bajo el límite (`ruff`/`C901`),
    no por otra razón de diseño.

    Con `procesos>1` cada hijo arma su PROPIA fábrica
    (`despacho_paralelo.inicializar_trabajador`) -- armar una acá también
    sería cargar un `MotorPii()` entero (~875 MB medidos, ver
    `despacho_paralelo`) en el padre para un ejecutor que nunca se usa, la
    copia N+1 que este tramo existe para evitar.
    """
    if motor is None:
        raise ValueError("motor es obligatorio cuando procesos <= 1 (camino secuencial, en este mismo proceso)")
    # puente id_alt_paciente -> id_paciente persistente contra
    # `vinculo_paciente` (ver docstring del módulo, fix post-merge): sobrevive
    # entre corridas separadas del script, a diferencia de `ResolutorClaves()`
    # en memoria.
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


def _despachar_grupos(
    *,
    corrida_id: str,
    grupos_a_despachar: Iterator[tuple[dict[str, str], ...]],
    procesos: int,
    entrada: Path,
    db_url: str | None,
    tope_bytes: int | None,
    cuarentena: EscritorCuarentena,
    directorio_marcador_pid: Path | None,
) -> tuple[list[dict[str, object]], int, int]:
    """Secuencial (`procesos<=1`, en este proceso) o paralelo (`procesos>1`,
    `ProcessPoolExecutor` vía `despacho_paralelo`). Extraído de `ejecutar()`
    por la misma razón que `_configurar_ejecutor_secuencial`: mantener la
    complejidad ciclomática de `ejecutar()` bajo el límite."""
    if procesos <= 1:
        print(f"Corrida {corrida_id}: procesando por grupo (secuencial)...", file=sys.stderr)
        # Despacho SECUENCIAL por grupo (openspec `paralelismo-de-procesamiento`
        # PR 2). `procesar_grupo` es la MISMA tarea Celery real que despachara
        # producción (llamada en directo, no `.delay()`: este script corre
        # sincrónico, sin broker). Antes se le pasaba `lanzamiento.referencias`
        # ENTERO en una sola llamada -- la carpeta completa como un solo lote --
        # y `procesar_lote` acumulaba en RAM los resueltos de la corrida entera
        # (con el corpus real, ~400.000 documentos de una sola vez). Llamarla una
        # vez POR GRUPO, iterando el generador en una sola pasada (nunca contando
        # de antemano), acota ese pico al tamaño de un grupo (un paciente) sin
        # cambiar el resultado: cada grupo sigue siendo un lote independiente con
        # su propio aislamiento de fallo.
        resultados: list[dict[str, object]] = []
        total_documentos = 0
        total_grupos = 0
        for grupo in grupos_a_despachar:
            total_documentos += len(grupo)
            total_grupos += 1
            resultados.extend(tareas.procesar_grupo(corrida_id, grupo))
        return resultados, total_documentos, total_grupos

    if db_url is None:
        raise ValueError(
            "db_url es obligatorio cuando procesos > 1: cada proceso hijo arma su propio Engine "
            "(una conexion de socket no sobrevive un pickle a traves del limite de proceso)"
        )
    print(f"Corrida {corrida_id}: procesando por grupo ({procesos} procesos)...", file=sys.stderr)
    return despacho_paralelo.despachar_en_paralelo(
        corrida_id=corrida_id,
        grupos=grupos_a_despachar,
        # `crear_pool` recibe el grado de concurrencia deseado -- no siempre
        # es `procesos`: la recuperación ante un pool roto pide un pool de
        # UN solo worker para aislar causalmente un crash (ver
        # `despacho_paralelo._EstadoDespacho._reprocesar_en_aislamiento`).
        crear_pool=lambda n: despacho_paralelo.crear_pool_de_trabajadores(
            entrada=entrada,
            db_url=db_url,
            tope_bytes=tope_bytes,
            procesos=n,
            directorio_marcador_pid=directorio_marcador_pid,
        ),
        procesos=procesos,
        cuarentena=cuarentena,
    )


def ejecutar(
    *,
    entrada: Path,
    engine: Engine,
    motor: MotorPii | None = None,
    pepper: bytes,
    tope_bytes: int | None = None,
    procesos: int = 1,
    db_url: str | None = None,
    directorio_marcador_pid: Path | None = None,
) -> int:
    """Lanza una corrida sobre `entrada` y procesa su inventario de punta a punta.

    Separado de `main()` para poder ejercitarlo con un motor/engine inyectados
    en tests (`tests/scripts/test_procesar_carpeta.py`) sin tocar argparse,
    variables de entorno, ni Postgres real. `tope_bytes=None` es "usar el
    default de producción" -- mismo convenio que `LanzadorCorrida`/`FuenteLocal`.

    `procesos=1` (default) mantiene el camino SECUENCIAL sin cambios --
    llama `tareas.procesar_grupo` en directo, en el mismo proceso, igual que
    antes del tramo 3. `procesos>1` despacha por
    `anonimizacion.trabajadores.despacho_paralelo.despachar_en_paralelo`
    (openspec `paralelismo-de-procesamiento` PR 3): cada grupo se procesa en
    un `ProcessPoolExecutor`, con recuperación automática si un hijo muere.
    En ese caso `db_url` es OBLIGATORIO -- cada proceso hijo arma su PROPIO
    `Engine` de Postgres (`construir_engine_postgres(db_url)`); el `engine`
    que recibe esta función nunca cruza el límite de proceso (una conexión
    de socket no sobrevive un pickle), solo se usa acá en el padre para
    crear el esquema y para registrar en `cuarentena` los grupos que se dan
    por perdidos tras agotar reintentos.

    `pepper` (el parámetro) solo se usa con `procesos<=1` -- con `procesos>1`
    cada hijo llama `obtener_pepper()` por su cuenta, leyendo
    `ANONIMIZACION_PEPPER`/`ANONIMIZACION_PEPPER_ARCHIVO` de SU PROPIO
    entorno heredado (ver `despacho_paralelo.inicializar_trabajador`), nunca
    del valor pasado acá: hacerlo viajar como argumento sería pasarlo por el
    mismo canal pickleado que cualquier otro dato, exactamente lo que la
    decisión de diseño evita. Quien llame con `procesos>1` debe asegurarse
    de que `ANONIMIZACION_PEPPER` esté seteada en el entorno del proceso que
    invoca esta función (`os.environ[...] = ...` en runtime alcanza -- ver
    `despacho_paralelo`, verificado con `spawn`).

    `directorio_marcador_pid` (`None` = producción): instrumentación de test
    -- ver el docstring de `despacho_paralelo.inicializar_trabajador`.
    """
    Base.metadata.create_all(engine, checkfirst=True)

    destino = EscritorPostgres(engine)
    cuarentena = EscritorCuarentena(engine)

    if procesos <= 1:
        _configurar_ejecutor_secuencial(
            entrada=entrada,
            motor=motor,
            pepper=pepper,
            destino=destino,
            cuarentena=cuarentena,
            tope_bytes=tope_bytes,
        )

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

    # `lanzamiento.referencias` es un GENERADOR de un solo uso (openspec
    # `paralelismo-de-procesamiento` PR 2, revisión adversarial hallazgo
    # crítico 2): ni `len()` ni un `bool()` directo funcionan sin consumirlo,
    # y consumirlo dos veces (una para contar, otra para despachar) lo
    # agotaría antes de procesar nada. `next(..., None)` extrae el primer
    # grupo -- o confirma que no hay ninguno -- sin renunciar a la pereza.
    iterador_grupos = iter(lanzamiento.referencias)
    primer_grupo = next(iterador_grupos, None)
    if primer_grupo is None:
        print("No se encontraron PDFs en esa carpeta.", file=sys.stderr)
        return 1

    # `lanzador.lanzar()` sólo inventaría -- no avanza a PROCESANDO (cierre de
    # silencio de auditoría, `fix/silencios-de-ingesta-y-panel`): inventariar
    # y procesar son cosas distintas, y quien sólo inventaría no puede
    # afirmar que está procesando. Este script es quien REALMENTE va a llamar
    # `procesar_grupo` a continuación, así que es quien debe marcarlo.
    lanzador.marcar_procesando(lanzamiento.corrida_id)

    grupos_a_despachar = itertools.chain([primer_grupo], iterador_grupos)

    resultados, total_documentos, total_grupos = _despachar_grupos(
        corrida_id=lanzamiento.corrida_id,
        grupos_a_despachar=grupos_a_despachar,
        procesos=procesos,
        entrada=entrada,
        db_url=db_url,
        tope_bytes=tope_bytes,
        cuarentena=cuarentena,
        directorio_marcador_pid=directorio_marcador_pid,
    )
    print(f"Corrida {lanzamiento.corrida_id}: {total_documentos} documento(s) en {total_grupos} grupo(s).", file=sys.stderr)

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

    # `motor` solo se carga en el padre para el camino SECUENCIAL
    # (`procesos<=1`): con `procesos>1` cada hijo del `ProcessPoolExecutor`
    # arma su PROPIO `MotorPii()` (`despacho_paralelo.inicializar_trabajador`)
    # -- cargarlo también acá sería una copia de más (~875 MB medidos, ver
    # docstring de `despacho_paralelo.grado_de_concurrencia_por_defecto`) que
    # el padre nunca usaría para procesar nada.
    motor: MotorPii | None = None
    if args.procesos <= 1:
        print("Motor de PII: cargando modelo de spaCy (puede tardar unos segundos)...", file=sys.stderr)
        motor = MotorPii()
    else:
        print(
            f"Motor de PII: se carga en cada uno de los {args.procesos} procesos hijos, no en este proceso.",
            file=sys.stderr,
        )

    print(f"Conectando a Postgres: {args.db_url}", file=sys.stderr)
    # `construir_engine_postgres` (openspec `paralelismo-de-procesamiento` PR 1)
    # arma el pool con `pool_pre_ping`/`pool_recycle` contra RDS -- ver el
    # docstring de esa función para el porqué un `sa.create_engine(url)` pelado
    # manda documentos válidos a cuarentena por una conexión muerta del pool.
    engine = construir_engine_postgres(args.db_url)

    return ejecutar(
        entrada=args.entrada,
        engine=engine,
        motor=motor,
        pepper=pepper,
        procesos=args.procesos,
        db_url=args.db_url,
    )


if __name__ == "__main__":
    raise SystemExit(main())
