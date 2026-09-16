"""Implementación real de `rutas_corridas.ServicioCorridas`. `crear_corrida` despacha
en un hilo de fondo vía `despacho_paralelo.despachar_en_paralelo`; `reintentar_corrida`
reusa el mismo camino sólo para los apartados con código reintentable."""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.ingesta.lanzador_corrida import (
    MARGEN_INACTIVIDAD_DEFAULT,
    CorridaEnCursoError,
    CorridaNoEncontradaError,
    LanzadorCorrida,
)
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import CorridaOrm
from anonimizacion.trabajadores import despacho_paralelo
from anonimizacion.web.embudo_corrida import Embudo, construir_embudo
from anonimizacion.web.reintento_corrida import construir_plan_reintento
from anonimizacion.web.rutas_corridas import EstadoCorridaPortal

Grupo = tuple[dict[str, str], ...]
# Misma forma que despacho_paralelo.despachar_en_paralelo; inyectable en tests que no
# ejercitan el despacho real.
FuncionDespacho = Callable[..., tuple[list[dict[str, object]], int, int]]

# Un tercio de MARGEN_INACTIVIDAD_DEFAULT: tres latidos de margen antes de considerar
# la corrida abandonada, para tolerar que uno se demore o falle sin depender de uno solo.
LATIDO_INTERVALO_SEG_DEFAULT = MARGEN_INACTIVIDAD_DEFAULT.total_seconds() / 3


def _emitir_latidos(
    *,
    repositorio: RepositorioCorridas,
    corrida_id: str,
    detener: threading.Event,
    intervalo_seg: float,
) -> None:
    """Hilo de fondo: llama `RepositorioCorridas.registrar_latido` cada `intervalo_seg`
    mientras `detener` no esté seteado -- señal de vida propia, independiente de que se
    haya escrito o no un estudio/cuarentena (necesario porque un corpus plano puede
    tardar más que `MARGEN_INACTIVIDAD_DEFAULT` sólo en listar, antes de procesar nada).
    Falla best-effort: un error transitorio de conexión no puede tumbar el despacho real."""
    while not detener.wait(timeout=intervalo_seg):
        try:
            repositorio.registrar_latido(corrida_id)
        except Exception:
            pass


def _despachar_y_cerrar(
    *,
    lanzador: LanzadorCorrida,
    corrida_id: str,
    grupos: Iterator[Grupo],
    entrada: Path,
    db_url: str,
    procesos: int,
    tope_bytes: int | None,
    despachador: FuncionDespacho,
    detener: threading.Event,
    latido_intervalo_seg: float = LATIDO_INTERVALO_SEG_DEFAULT,
    registro_de_pool: despacho_paralelo.RegistroDePool | None = None,
) -> None:
    """Corre en un hilo de fondo lanzado por `ServicioCorridasReal.crear_corrida`. Es un
    hilo, no un `ProcessPoolExecutor` anidado: el trabajo CPU-bound ya corre en procesos
    hijos propios de `despachador`, así que este hilo sólo orquesta (I/O-bound desde la
    perspectiva de este proceso) sin competir por el GIL con el resto de las peticiones
    HTTP. Un `Exception` inesperado marca la corrida `FALLIDA` y se vuelve a lanzar para
    quedar visible en stderr. Si `detener` está seteado al retornar, el despacho se
    cortó a propósito -- cierra `FALLIDA` también, nunca `COMPLETADA` sin evidencia."""
    detener_latido = threading.Event()
    hilo_latido = threading.Thread(
        target=_emitir_latidos,
        kwargs={
            "repositorio": lanzador.repositorio,
            "corrida_id": corrida_id,
            "detener": detener_latido,
            "intervalo_seg": latido_intervalo_seg,
        },
        daemon=True,
    )
    hilo_latido.start()
    try:
        lanzador.marcar_procesando(corrida_id)
        resultados, _total_documentos, _total_grupos = despachador(
            corrida_id=corrida_id,
            grupos=grupos,
            crear_pool=lambda n: despacho_paralelo.crear_pool_de_trabajadores(
                entrada=entrada,
                db_url=db_url,
                tope_bytes=tope_bytes,
                procesos=n,
            ),
            procesos=procesos,
            cuarentena=lanzador.cuarentena,
            detener=detener,
            registro_de_pool=registro_de_pool,
        )
    except Exception:
        try:
            lanzador.marcar_fallida(corrida_id)
        except Exception:
            pass  # ya hay una excepcion real en curso; no la tapamos con esta
        raise
    else:
        if detener.is_set():
            lanzador.marcar_fallida(corrida_id)
        else:
            hubo_cuarentena = any(resultado["estado"] != "exito" for resultado in resultados)
            lanzador.marcar_finalizada(corrida_id, hubo_cuarentena=hubo_cuarentena)
    finally:
        detener_latido.set()
        hilo_latido.join(timeout=5)


def _leer_estado_corrida(motor: Engine, id_corrida: str) -> str | None:
    """Sólo el estado administrativo (`corrida.estado`), distinto de
    `documento_corrida.estado` (la máquina de estados del documento, nunca leída por el embudo)."""
    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, id_corrida)
    return fila.estado if fila is not None else None


def _serializar_embudo(embudo: Embudo, estado: str) -> dict[str, object]:
    estimacion: dict[str, object] = {"situacion": embudo.estimacion.situacion}
    if embudo.estimacion.situacion == "disponible":
        estimacion["restante_seg_min"] = embudo.estimacion.restante_seg_min
        estimacion["restante_seg_max"] = embudo.estimacion.restante_seg_max
    return {
        "corrida_id": embudo.corrida_id,
        "estado": estado,
        "generado_en": embudo.generado_en.isoformat(),
        "entraron": embudo.entraron,
        "publicados": embudo.publicados,
        "apartados": embudo.apartados,
        "residuo": embudo.residuo,
        "cierra": embudo.cierra,
        "marcha": embudo.marcha,
        "etapas": [
            {
                "etapa": perdida.etapa,
                "llegaron": perdida.llegaron,
                "apartados": perdida.apartados,
                "codigos": dict(perdida.codigos),
            }
            for perdida in embudo.etapas
        ],
        "throughput_por_hora": dict(embudo.throughput_por_hora),
        "estimacion": estimacion,
        # Aviso, no falla el contrato: nunca participan de apartados/residuo.
        "publicados_incompletos": embudo.publicados_incompletos,
        "campos_no_extraidos": dict(embudo.campos_no_extraidos),
    }


def construir_payload_embudo(motor: Engine, id_corrida: str) -> dict[str, object] | None:
    """`None` si la corrida no existe -- la ruta lo traduce a 404."""
    estado = _leer_estado_corrida(motor, id_corrida)
    if estado is None:
        return None
    embudo = construir_embudo(motor, id_corrida)
    return _serializar_embudo(embudo, estado)


@dataclass(frozen=True)
class ResultadoReintento(EstadoCorridaPortal):
    """`EstadoCorridaPortal` + el desglose de reintentados/descartados. Subclase, no un
    campo nuevo: `crear_corrida`/`consultar_corrida` deben seguir devolviendo sólo las
    cuatro claves de siempre."""

    reintentados: int = 0
    descartados_deterministicos: int = 0
    descartados_por_codigo: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ServicioCorridasReal:
    """Implementación real: crea, despacha y consulta el embudo de verdad.

    `db_url`: cada proceso hijo arma su propio `Engine` (una conexión de socket no
    sobrevive el pickle entre procesos). `_evento_apagado`: un solo `threading.Event`
    compartido por todos los despachos, nunca se resetea (apagado es del proceso, no
    de una corrida puntual). `_lock_creacion` cierra la ventana TOCTOU entre leer
    `listar_corridas_no_terminales` y crear la corrida dentro de este proceso -- no
    protege contra un escritor externo (`scripts/procesar_carpeta.py`), donde la
    protección real es que el `SELECT` ve la fila en cuanto existe."""

    lanzador: LanzadorCorrida
    motor: Engine
    db_url: str
    procesos: int
    tope_bytes: int | None = None
    despachador: FuncionDespacho = despacho_paralelo.despachar_en_paralelo
    latido_intervalo_seg: float = LATIDO_INTERVALO_SEG_DEFAULT
    _hilos_en_curso: list[threading.Thread] = field(default_factory=list)
    _evento_apagado: threading.Event = field(default_factory=threading.Event)
    _lock_creacion: threading.Lock = field(default_factory=threading.Lock)
    # Referencia al pool del despacho en curso, para terminarlo a la fuerza si el
    # apagado cooperativo se agota -- ver terminar_despachos_a_la_fuerza.
    _registro_de_pool: despacho_paralelo.RegistroDePool = field(default_factory=despacho_paralelo.RegistroDePool)

    def crear_corrida(self, ruta_autorizada: str) -> EstadoCorridaPortal:
        """Crea la corrida, inventaría el primer grupo, y despacha el resto en segundo
        plano. Rechaza si ya hay otra corrida activa (`CorridaEnCursoError`, gate "una
        corrida a la vez"). El generador de referencias se consume perezosamente
        (`itertools.chain`): sólo el primer grupo se inventaría en el hilo de la
        petición, el resto en el hilo de fondo a medida que el despachador avanza."""
        with self._lock_creacion:
            activas = self.lanzador.repositorio.listar_corridas_no_terminales()
            if activas:
                raise CorridaEnCursoError(activas[0].id_corrida)

            ruta = Path(ruta_autorizada)
            resultado = self.lanzador.lanzar(ruta)
            iterador_grupos = iter(resultado.referencias)
            primer_grupo = next(iterador_grupos, None)
        if primer_grupo is not None:
            grupos_a_despachar = itertools.chain([primer_grupo], iterador_grupos)
            hilo = threading.Thread(
                target=_despachar_y_cerrar,
                kwargs={
                    "lanzador": self.lanzador,
                    "corrida_id": resultado.corrida_id,
                    "grupos": grupos_a_despachar,
                    "entrada": ruta,
                    "db_url": self.db_url,
                    "procesos": self.procesos,
                    "tope_bytes": self.tope_bytes,
                    "despachador": self.despachador,
                    "detener": self._evento_apagado,
                    "latido_intervalo_seg": self.latido_intervalo_seg,
                    "registro_de_pool": self._registro_de_pool,
                },
                # daemon=True NO acota el apagado por sí solo (medido: el atexit de
                # ProcessPoolExecutor espera al pool activo igual, ~114s colgado). El
                # apagado real es el mecanismo de dos pasos en servir_panel.py::main:
                # solicitar_apagado()+esperar_despachos_en_curso(timeout), y si eso se
                # agota, terminar_despachos_a_la_fuerza(). daemon=True sólo cubre el
                # caso en que el proceso entero muere antes de llegar a ese mecanismo.
                daemon=True,
            )
            self._hilos_en_curso.append(hilo)
            hilo.start()
        return self.consultar_corrida(resultado.corrida_id)

    def esperar_despachos_en_curso(self, timeout: float | None = None) -> None:
        """Bloquea hasta que todos los despachos en segundo plano lanzados por este
        servicio terminen (o hasta `timeout`, por hilo)."""
        for hilo in list(self._hilos_en_curso):
            hilo.join(timeout=timeout)

    def hay_despachos_en_curso(self) -> bool:
        """`True` si algún hilo de despacho lanzado por este servicio sigue vivo."""
        return any(hilo.is_alive() for hilo in self._hilos_en_curso)

    def solicitar_apagado(self) -> None:
        """Señala a todos los despachos en curso (y a los que arranquen después) que
        dejen de tomar grupos nuevos. No cancela trabajo ya en vuelo -- ver
        `terminar_despachos_a_la_fuerza` para cuando eso no alcanza."""
        self._evento_apagado.set()

    def terminar_despachos_a_la_fuerza(self) -> int:
        """Termina a la fuerza los procesos hijos vivos del despacho en curso, cuando
        `solicitar_apagado()` (cooperativo) no alcanza -- un worker ocupado no se
        interrumpe solo. El trabajo en vuelo se pierde; la corrida cierra `FALLIDA`,
        nunca `COMPLETADA`. Devuelve la cantidad de procesos señalados."""
        return self._registro_de_pool.terminar_a_la_fuerza()

    def consultar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
        estado = _leer_estado_corrida(self.motor, id_corrida)
        embudo = construir_embudo(self.motor, id_corrida)
        return EstadoCorridaPortal(
            id_corrida=id_corrida,
            estado=estado or "desconocida",
            # Mismo residuo con signo del embudo: un descuadre debe verse acá también.
            documentos_pendientes=embudo.residuo,
            cuarentenas=embudo.apartados,
        )

    def reintentar_corrida(self, id_corrida: str) -> ResultadoReintento:
        """Reencola sólo los apartados con código reintentable de `id_corrida`, mismo
        gate y camino de despacho que `crear_corrida`. Levanta `CorridaEnCursoError` si
        hay otra corrida no terminal (incluye `id_corrida` misma) y
        `CorridaNoEncontradaError` si no existe."""
        with self._lock_creacion:
            activas = self.lanzador.repositorio.listar_corridas_no_terminales()
            if activas:
                raise CorridaEnCursoError(activas[0].id_corrida)

            plan = construir_plan_reintento(self.motor, id_corrida)
            if plan is None:
                raise CorridaNoEncontradaError(id_corrida)

            if plan.reintentables and not plan.ruta_autorizada:
                # Corrida previa a la migración 0011 (sin backfill): fallar ruidoso
                # en vez de adivinar la raíz autorizada.
                raise RuntimeError(
                    f"reintentar_corrida: {id_corrida} no tiene ruta_autorizada persistida "
                    "(corrida anterior a la migracion 0011) -- no se puede reintentar sin la "
                    "raiz autorizada original"
                )

            if plan.reintentables:
                # Transicionar a PROCESANDO dentro del lock, antes de soltar -- cierra
                # la misma ventana TOCTOU que crear_corrida. Idempotente si ya está
                # en PROCESANDO, así que _despachar_y_cerrar no vuelve a fallar por esto.
                self.lanzador.marcar_procesando(id_corrida)

        if plan.reintentables:
            grupo: Grupo = tuple(plan.reintentables)  # UN grupo: el coordinador reagrupa por paciente
            hilo = threading.Thread(
                target=_despachar_y_cerrar,
                kwargs={
                    "lanzador": self.lanzador,
                    "corrida_id": id_corrida,
                    "grupos": iter([grupo]),
                    "entrada": Path(plan.ruta_autorizada),
                    "db_url": self.db_url,
                    "procesos": self.procesos,
                    "tope_bytes": self.tope_bytes,
                    "despachador": self.despachador,
                    "detener": self._evento_apagado,
                    "latido_intervalo_seg": self.latido_intervalo_seg,
                    "registro_de_pool": self._registro_de_pool,
                },
                daemon=True,
            )
            self._hilos_en_curso.append(hilo)
            hilo.start()

        estado = self.consultar_corrida(id_corrida)
        return ResultadoReintento(
            id_corrida=estado.id_corrida,
            estado=estado.estado,
            documentos_pendientes=estado.documentos_pendientes,
            cuarentenas=estado.cuarentenas,
            reintentados=len(plan.reintentables),
            descartados_deterministicos=plan.total_descartados,
            descartados_por_codigo=dict(plan.descartados_por_codigo),
        )
