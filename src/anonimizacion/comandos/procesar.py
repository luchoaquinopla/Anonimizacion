"""Composición del subcomando `anonimizacion procesar` (`cli.py` resuelve
banderas/config y llama a `ejecutar()` con argumentos con nombre). Crea el esquema con
`create_all` (no Alembic: válido para pruebas rápidas, no producción) y sólo escribe a
Postgres.

Usa `ResolutorClavesPostgres`, no `ResolutorClaves()` en memoria -- ver
`sdd/pdf-pii-anonymization/apply-progress`, sección "Fix: persistencia del puente
id_alt_paciente en Postgres entre corridas": el puente debe persistir entre corridas
separadas, no sólo dentro de un mismo lote. `ejecutar()` cierra la corrida en los tres
desenlaces posibles (COMPLETADA/COMPLETADA_CON_CUARENTENA/FALLIDA) -- antes quedaba
`activa=true` para siempre si nunca se llamaba a marcar_finalizada/marcar_fallida."""

from __future__ import annotations

import itertools
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine

from anonimizacion.configuracion import _DB_URL_DEFAULT
from anonimizacion.ingesta.lanzador_corrida import CorridaEnCursoError, LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesPostgres
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.trabajadores import despacho_paralelo, tareas

__all__ = ["ejecutar", "_DB_URL_DEFAULT"]


def _configurar_ejecutor_secuencial(
    *,
    entrada: Path,
    motor: MotorPii | None,
    pepper: bytes,
    destino: EscritorPostgres,
    cuarentena: EscritorCuarentena,
    tope_bytes: int | None,
) -> None:
    """Arma y registra la fábrica de `EjecutorPipeline` en este proceso, sólo para el
    camino secuencial (`procesos<=1`). Extraído de `ejecutar()` para mantener su
    complejidad ciclomática bajo el límite."""
    if motor is None:
        raise ValueError("motor es obligatorio cuando procesos <= 1 (camino secuencial, en este mismo proceso)")
    # Puente id_alt_paciente -> id_paciente persistente, a diferencia de ResolutorClaves() en memoria.
    resolutor = ResolutorClavesPostgres(destino)

    # Misma raíz de composición que el trabajador -- armarlo a mano dejaba a este
    # script sin validación de episodio mientras el banco de carga sí la tenía.
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
    `ProcessPoolExecutor` vía `despacho_paralelo`). Extraído de `ejecutar()` para
    mantener su complejidad ciclomática bajo el límite."""
    if procesos <= 1:
        print(f"Corrida {corrida_id}: procesando por grupo (secuencial)...", file=sys.stderr)
        # procesar_grupo se llama una vez POR GRUPO (nunca con el generador entero):
        # acota el pico de RAM al tamaño de un grupo en vez de la corrida completa.
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
    # Sin esto, el costo de recargar MotorPii completo tras un hijo muerto es invisible.
    metricas_despacho = despacho_paralelo.MetricasDespacho()
    resultado = despacho_paralelo.despachar_en_paralelo(
        corrida_id=corrida_id,
        grupos=grupos_a_despachar,
        # No siempre es `procesos`: la recuperación de un pool roto pide 1 solo worker.
        crear_pool=lambda n: despacho_paralelo.crear_pool_de_trabajadores(
            entrada=entrada,
            db_url=db_url,
            tope_bytes=tope_bytes,
            procesos=n,
            directorio_marcador_pid=directorio_marcador_pid,
        ),
        procesos=procesos,
        cuarentena=cuarentena,
        metricas=metricas_despacho,
    )
    if metricas_despacho.recreaciones_de_pool_principal:
        print(
            f"Corrida {corrida_id}: recuperación ante procesos muertos -- "
            f"{metricas_despacho.recreaciones_de_pool_principal} recreación(es) del pool principal, "
            f"{metricas_despacho.reprocesos_en_aislamiento} reproceso(s) en aislamiento "
            "(cada uno recarga el modelo de PII completo, ~875 MB medidos).",
            file=sys.stderr,
        )
    return resultado


def _despachar_y_cerrar_corrida(
    *,
    lanzador: LanzadorCorrida,
    corrida_id: str,
    grupos_a_despachar: Iterator[tuple[dict[str, str], ...]],
    procesos: int,
    entrada: Path,
    db_url: str | None,
    tope_bytes: int | None,
    cuarentena: EscritorCuarentena,
    directorio_marcador_pid: Path | None,
) -> tuple[list[dict[str, object]], int, int]:
    """Marca `PROCESANDO`, despacha y cierra la corrida en el desenlace que
    corresponda -- simétrico de `web/servicio_corridas.py::_despachar_y_cerrar`.
    Una excepción inesperada cierra `FALLIDA` y se re-lanza sin tragarse el error."""
    lanzador.marcar_procesando(corrida_id)
    try:
        resultados, total_documentos, total_grupos = _despachar_grupos(
            corrida_id=corrida_id,
            grupos_a_despachar=grupos_a_despachar,
            procesos=procesos,
            entrada=entrada,
            db_url=db_url,
            tope_bytes=tope_bytes,
            cuarentena=cuarentena,
            directorio_marcador_pid=directorio_marcador_pid,
        )
    except Exception:
        try:
            lanzador.marcar_fallida(corrida_id)
        except Exception:
            pass  # ya hay una excepcion real en curso; no la tapamos con esta
        raise

    hubo_cuarentena = any(resultado["estado"] != "exito" for resultado in resultados)
    lanzador.marcar_finalizada(corrida_id, hubo_cuarentena=hubo_cuarentena)
    return resultados, total_documentos, total_grupos


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
    `procesos=1` corre secuencial en este proceso; `procesos>1` despacha por
    `despacho_paralelo` (requiere `db_url`: cada hijo arma su propio `Engine`, una
    conexión de socket no sobrevive el pickle). Con `procesos>1`, `pepper` no viaja
    al hijo: cada uno llama `obtener_pepper()` leyendo su propio entorno heredado."""
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

    # Único punto donde nace una corrida: crea la fila, inventaría, y devuelve las
    # referencias en la forma exacta que exige procesar_grupo.
    lanzador = LanzadorCorrida(
        repositorio=RepositorioCorridas(engine),
        cuarentena=cuarentena,
        **({"tope_bytes": tope_bytes} if tope_bytes is not None else {}),
    )
    print(f"Lanzando corrida sobre {entrada}...", file=sys.stderr)
    try:
        lanzamiento = lanzador.lanzar(entrada)
    except CorridaEnCursoError as error:
        # La única protección real contra dos corridas simultáneas la impone la base
        # (ux_corrida_una_activa); acá sólo se traduce a un mensaje claro.
        print(f"No se puede lanzar esta corrida: {error}", file=sys.stderr)
        return 2

    # Generador de un solo uso: next(..., None) confirma si hay algo sin consumirlo dos veces.
    iterador_grupos = iter(lanzamiento.referencias)
    primer_grupo = next(iterador_grupos, None)
    if primer_grupo is None:
        print("No se encontraron PDFs en esa carpeta.", file=sys.stderr)
        # Sin cerrar acá, la corrida queda activa=true para siempre y bloquea la próxima.
        lanzador.marcar_fallida(lanzamiento.corrida_id)
        return 1

    grupos_a_despachar = itertools.chain([primer_grupo], iterador_grupos)

    resultados, total_documentos, total_grupos = _despachar_y_cerrar_corrida(
        lanzador=lanzador,
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


# La composición completa vive en cli.py::_comando_procesar.
