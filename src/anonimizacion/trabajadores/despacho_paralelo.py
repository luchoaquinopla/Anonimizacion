"""Despacho multiproceso de grupos. Módulo real e importable a propósito: `spawn`
picklea `initializer`/la función sometida a `submit()` por REFERENCIA de módulo
(`nombre_de_modulo`, resuelto por el hijo con `import_module`). Una función definida en
un módulo cargado dinámicamente (`spec_from_file_location`) NO es picklable para un
hijo `spawn` -- rompe el pool ENTERO (`BrokenProcessPool`), no sólo esa tarea. Por eso
todo lo que cruza el límite de proceso vive acá, a nivel de módulo, nunca
closures/lambdas (tampoco picklables)."""

# Procesos del SO y no una cola (Celery+Redis, retirada): nada pasa por un broker y el
# operador es un médico. Ver docs/pipeline.md, "Concurrencia".
from __future__ import annotations

import itertools
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento, EtapaDocumento
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import DestinoCuarentena
from anonimizacion.pipeline.resultado import FalloDocumento
from anonimizacion.pseudonimizacion.almacen_pepper import obtener_pepper
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesPostgres
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres, construir_engine_postgres

# `Referencia` es la forma exacta que exige `tareas.procesar_grupo`:
# `{id_documento, uri, sha256}`. `Grupo` es una tupla de referencias -- misma
# forma que produce `LanzadorCorrida.lanzar()` (ver su docstring).
Referencia = Mapping[str, str]
Grupo = tuple[Referencia, ...]
FuncionTrabajo = Callable[[str, Grupo], list[dict[str, object]]]

# Default = min(núcleos_lógicos // 2, tope conservador). Validar sólo contra núcleos
# deja pasar valores que agotan la memoria sin aviso -- el techo real es la memoria,
# no los núcleos.
# Invariante: «Cantidad de procesos y reintentos» (Obsidian, Invariantes medidos).
_TOPE_DEFAULT_CONSERVADOR = 4
# Tope duro = min(2x núcleos lógicos, presupuesto de memoria // memoria por proceso).
_MULTIPLICADOR_TOPE_DURO = 2
# MotorPii (spaCy+Presidio) consume ~875 MB de RSS por proceso, medido con
# K32GetProcessMemoryInfo (ctypes).
# Invariante: «Memoria por proceso del detector» (Obsidian, Invariantes medidos).
_MEMORIA_ESTIMADA_POR_PROCESO_MB = 875
_PRESUPUESTO_MEMORIA_TOPE_DURO_MB = 8192
# Reintentos EN AISLAMIENTO ante BrokenProcessPool; el intento en el pool principal
# nunca cuenta acá. MAX_REINTENTOS_POR_GRUPO=1 con comparación `>=` (no `>`) da 2
# cargas totales -- intento normal + 1 reintento aislado -- no 3. El culpable de un
# pool roto se reprocesa siempre solo, nunca junto a un grupo sano (atribución
# causal, no el primero que itera un `set` sin orden).
MAX_REINTENTOS_POR_GRUPO = 1


def grado_de_concurrencia_por_defecto() -> int:
    """Default conservador de `--procesos` -- ver el razonamiento medido arriba."""
    logicos = os.cpu_count() or 2
    return max(1, min(logicos // 2, _TOPE_DEFAULT_CONSERVADOR))


def tope_duro_concurrencia() -> int:
    """El más chico entre 2x núcleos lógicos y el presupuesto de memoria
    (`_PRESUPUESTO_MEMORIA_TOPE_DURO_MB` // `_MEMORIA_ESTIMADA_POR_PROCESO_MB`)."""
    tope_por_nucleos = _MULTIPLICADOR_TOPE_DURO * (os.cpu_count() or 1)
    tope_por_memoria = _PRESUPUESTO_MEMORIA_TOPE_DURO_MB // _MEMORIA_ESTIMADA_POR_PROCESO_MB
    return min(tope_por_nucleos, tope_por_memoria)


def validar_grado_concurrencia(procesos: int) -> int:
    """Valida `--procesos`; lanza `ValueError` fuera de [1, tope_duro]."""
    if procesos < 1:
        raise ValueError("procesos debe ser al menos 1")
    tope = tope_duro_concurrencia()
    if procesos > tope:
        raise ValueError(
            f"procesos={procesos} supera el tope duro ({tope} en esta maquina: el "
            "menor entre 2x nucleos logicos y el presupuesto de memoria de "
            f"{_PRESUPUESTO_MEMORIA_TOPE_DURO_MB} MB // {_MEMORIA_ESTIMADA_POR_PROCESO_MB} MB "
            "por copia de es_core_news_lg). Pasado ese punto cada proceso extra solo "
            "compra latencia de red (el termino de CPU del modelo de speedup deja "
            "de mejorar) y cuesta una copia mas del modelo en RAM -- medir el pico "
            "de memoria real antes de subirlo."
        )
    return procesos


# --- Composición del hijo ---------------------------------------------------


def inicializar_trabajador(
    entrada: Path,
    db_url: str,
    tope_bytes: int | None,
    directorio_marcador_pid: Path | None = None,
) -> None:
    """`initializer` de `ProcessPoolExecutor`: corre una vez por hijo, antes de la
    primera tarea. Construye acá -- no en el padre -- todo lo no picklable o caro:
    `MotorPii`, el `Engine` de Postgres y el pepper (leído por el hijo de su propio
    entorno heredado, nunca recibido como argumento: viajaría pickleado, otra copia
    del secreto en tránsito). `directorio_marcador_pid`
    (`None` = producción) es instrumentación de test: cada hijo deja un archivo con su
    propio PID, para confirmar que dos grupos corrieron en procesos genuinamente distintos."""
    pepper = obtener_pepper()
    motor = MotorPii()
    engine = construir_engine_postgres(db_url)
    destino = EscritorPostgres(engine)
    cuarentena = EscritorCuarentena(engine)
    resolutor = ResolutorClavesPostgres(destino)

    # Import diferido: evita un ciclo con trabajadores.tareas.
    from anonimizacion.trabajadores import tareas

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

    if directorio_marcador_pid is not None:
        (directorio_marcador_pid / str(os.getpid())).touch()


def procesar_grupo_en_trabajador(corrida_id: str, grupo: Grupo) -> list[dict[str, object]]:
    """Función de módulo (picklable) que un hijo ya inicializado ejecuta por grupo.
    Delega en `tareas.procesar_grupo`; un closure/lambda acá no sería picklable."""
    from anonimizacion.trabajadores import tareas

    return tareas.procesar_grupo(corrida_id, grupo)


def crear_pool_de_trabajadores(
    *,
    entrada: Path,
    db_url: str,
    tope_bytes: int | None,
    procesos: int,
    directorio_marcador_pid: Path | None = None,
) -> ProcessPoolExecutor:
    """Fábrica de producción: un `initializer` por hijo, nunca un motor/engine
    compartido entre procesos."""
    return ProcessPoolExecutor(
        max_workers=procesos,
        initializer=inicializar_trabajador,
        initargs=(entrada, db_url, tope_bytes, directorio_marcador_pid),
    )


def _error_grupo_perdido(referencia: Referencia, corrida_id: str) -> ErrorDocumento:
    """`ErrorDocumento` de un grupo dado por perdido, usado tanto para `cuarentena`
    como para el `resumen_trazable()` de `resultados` -- ambas superficies describen
    el mismo fallo. `codigo=PROCESO_INTERRUMPIDO`, no `ERROR_TRANSITORIO_AGOTADO`: ese
    código ya significa un error dentro del pipeline sobre un documento que sí corrió."""
    return ErrorDocumento(
        id_documento=referencia["id_documento"],
        # etapa MUST ser de ETAPAS_EMBUDO: un str libre suma al total pero desaparece del desglose.
        etapa=EtapaDocumento.DESPACHO,
        codigo=CodigoErrorDocumento.PROCESO_INTERRUMPIDO,
        corrida_id=corrida_id,
    )


@dataclass
class MetricasDespacho:
    """Contadores de eventos de RECUPERACIÓN del despachador, en el padre -- sin
    equivalente en el ejecutor. La recuperación recarga `MotorPii` completo por cada
    afectado: medido, 3 crashes sobre 48 grupos produjeron 25 PIDs de hijos distintos
    contra 4 en estado estable (~21 recargas de más). Sin lock: un solo hilo, un solo
    proceso padre."""

    recreaciones_de_pool_principal: int = 0
    reprocesos_en_aislamiento: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "recreaciones_de_pool_principal": self.recreaciones_de_pool_principal,
            "reprocesos_en_aislamiento": self.reprocesos_en_aislamiento,
        }


@dataclass
class RegistroDePool:
    """Referencia al `ProcessPoolExecutor` actualmente activo. Hace falta porque
    `detener` sólo evita tomar grupos nuevos -- no interrumpe un worker ya ocupado
    (medido: el `atexit` de `concurrent.futures.process` cuelga ~114s igual esperando
    el pool activo). Mutado en el lugar, nunca reasignado. `terminar_a_la_fuerza` usa
    la API privada `_processes`: si una versión futura de CPython la cambia, falla en
    silencio (devuelve 0) en vez de romper."""

    pool: ProcessPoolExecutor | None = None

    def terminar_a_la_fuerza(self) -> int:
        """Termina (`.terminate()`, sin cierre limpio) cada proceso hijo vivo del pool
        actual. El trabajo en vuelo se pierde. Devuelve la cantidad señalada, sin
        esperar a que mueran. Best-effort: si `pool` no expone `_processes`, devuelve
        0 en vez de lanzar."""
        if self.pool is None:
            return 0
        procesos = getattr(self.pool, "_processes", None)
        if not procesos:
            return 0
        terminados = 0
        for proceso in list(procesos.values()):
            if proceso.is_alive():
                proceso.terminate()
                terminados += 1
        return terminados


@dataclass
class _EstadoDespacho:
    """Estado mutable de una corrida de `despachar_en_paralelo`, en su propia clase
    (no closures) para que cada método tenga su propio presupuesto de complejidad
    ciclomática."""

    corrida_id: str
    grupos: Iterator[Grupo]
    crear_pool: Callable[[int], ProcessPoolExecutor]
    procesos: int
    cuarentena: DestinoCuarentena
    funcion_trabajo: FuncionTrabajo
    metricas: MetricasDespacho = field(default_factory=MetricasDespacho)
    detener: threading.Event | None = None
    registro_de_pool: RegistroDePool | None = None

    resultados: list[dict[str, object]] = field(default_factory=list)
    total_documentos: int = 0
    total_grupos: int = 0
    contador_indices: Iterator[int] = field(default_factory=itertools.count)
    intentos_por_grupo: dict[int, int] = field(default_factory=dict)
    en_vuelo: dict[Future[list[dict[str, object]]], tuple[int, Grupo]] = field(default_factory=dict)
    pool: ProcessPoolExecutor | None = None

    def _reponer(self) -> None:
        # Si se pidió detener, no se toma ningún grupo nuevo -- lo en vuelo drena solo.
        if self.detener is not None and self.detener.is_set():
            return
        grupo = next(self.grupos, None)
        if grupo is None:
            return
        indice = next(self.contador_indices)
        self.intentos_por_grupo[indice] = 0
        futuro = self.pool.submit(self.funcion_trabajo, self.corrida_id, grupo)
        self.en_vuelo[futuro] = (indice, grupo)

    def _dar_por_perdido(self, indice: int, grupo: Grupo) -> None:
        for referencia in grupo:
            error = _error_grupo_perdido(referencia, self.corrida_id)
            self.cuarentena.registrar(error)
            self.resultados.append(
                FalloDocumento(
                    id_documento=referencia["id_documento"],
                    error=error,
                    timestamp=datetime.now(timezone.utc),
                ).resumen_trazable()
            )
        self.total_documentos += len(grupo)
        self.total_grupos += 1
        # Sin este pop, intentos_por_grupo crece sin límite durante toda la corrida.
        self.intentos_por_grupo.pop(indice, None)

    def _aceptar_exito(self, indice: int, grupo: Grupo, parcial: list[dict[str, object]]) -> None:
        self.resultados.extend(parcial)
        self.total_documentos += len(grupo)
        self.total_grupos += 1
        self.intentos_por_grupo.pop(indice, None)

    def _reprocesar_en_aislamiento(self, indice: int, grupo: Grupo) -> None:
        """Reprocesa un grupo SOLO, en su propio pool de un worker -- la única forma de
        atribuir causalmente un crash. `wait()` convierte los futuros a un `set`: cuál
        "sale primero" es orden de hash, no de causalidad -- tratar al primero como
        culpable manda estudios sanos a cuarentena por compartir pool con uno tóxico.
        Si vuelve a morir solo, es su propia culpa; si no, nunca fue culpable y su
        contador de reintentos no se toca. Secuencial, un grupo a la vez."""
        self.metricas.reprocesos_en_aislamiento += 1
        pool_aislado = self.crear_pool(1)
        futuro = pool_aislado.submit(self.funcion_trabajo, self.corrida_id, grupo)
        try:
            parcial = futuro.result()
        except BrokenProcessPool:
            pool_aislado.shutdown(wait=False, cancel_futures=True)
            self.intentos_por_grupo[indice] = self.intentos_por_grupo.get(indice, 0) + 1
            # `>=`, no `>`: con `>` serían 3 cargas totales para un grupo tóxico, no 2.
            if self.intentos_por_grupo[indice] >= MAX_REINTENTOS_POR_GRUPO:
                self._dar_por_perdido(indice, grupo)
            else:
                self._reprocesar_en_aislamiento(indice, grupo)
        else:
            pool_aislado.shutdown(wait=True)
            self._aceptar_exito(indice, grupo, parcial)

    def _asignar_pool(self, pool: ProcessPoolExecutor | None) -> None:
        """Único punto que reasigna `self.pool` -- mantiene `self.registro_de_pool`
        sincronizado con el pool vigente, incluso tras una recreación."""
        self.pool = pool
        if self.registro_de_pool is not None:
            self.registro_de_pool.pool = pool

    def _recuperar_de_pool_roto(self, indice: int, grupo: Grupo) -> None:
        """Descarta el pool roto y reprocesa en aislamiento todo lo que seguía en
        vuelo (`afectados`). Siempre recrea el pool y repone la ventana a ancho
        completo -- sin esto, un grupo perdido degradaba la corrida a (procesos - 1)
        para siempre. Excepción: si `detener` ya está seteado, el `BrokenProcessPool`
        puede ser consecuencia deliberada de un apagado forzado -- los afectados se
        dan por perdidos sin recrear ni reprocesar, `self.pool` queda en `None`."""
        afectados = [(indice, grupo), *self.en_vuelo.values()]
        self.en_vuelo.clear()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.metricas.recreaciones_de_pool_principal += 1

        if self.detener is not None and self.detener.is_set():
            for indice_afectado, grupo_afectado in afectados:
                self._dar_por_perdido(indice_afectado, grupo_afectado)
            self._asignar_pool(None)
            return

        for indice_afectado, grupo_afectado in afectados:
            self._reprocesar_en_aislamiento(indice_afectado, grupo_afectado)

        self._asignar_pool(self.crear_pool(self.procesos))
        for _ in range(self.procesos):
            self._reponer()

    def _procesar_terminado(self, futuro: Future[list[dict[str, object]]]) -> None:
        entrada_en_vuelo = self.en_vuelo.pop(futuro, None)
        if entrada_en_vuelo is None:
            # Ya fue reencolado/dado por perdido junto con otro futuro de este mismo
            # lote: un pool roto marca varios futuros a la vez, no de a uno.
            return
        indice, grupo = entrada_en_vuelo
        try:
            parcial = futuro.result()
        except BrokenProcessPool:
            self._recuperar_de_pool_roto(indice, grupo)
        else:
            self._aceptar_exito(indice, grupo, parcial)
            self._reponer()

    def ejecutar(self) -> tuple[list[dict[str, object]], int, int]:
        self._asignar_pool(self.crear_pool(self.procesos))
        for _ in range(self.procesos):
            self._reponer()

        while self.en_vuelo:
            terminados, _ = wait(list(self.en_vuelo.keys()), return_when=FIRST_COMPLETED)
            pool_antes = self.pool
            for futuro in terminados:
                self._procesar_terminado(futuro)
                if self.pool is not pool_antes:
                    # _recuperar_de_pool_roto ya resolvió todo lo que seguía en vuelo
                    # en el pool viejo -- el resto de este lote pertenece a ese pool
                    # descartado. Volver a wait() sobre el pool nuevo (o salir si no
                    # quedó ninguno).
                    break

        # self.pool puede ser None: _recuperar_de_pool_roto lo deja así cuando el
        # apagado forzado no tiene un pool "principal" que cerrar de nuevo.
        if self.pool is not None:
            self.pool.shutdown(wait=True)
        return self.resultados, self.total_documentos, self.total_grupos


def despachar_en_paralelo(
    *,
    corrida_id: str,
    grupos: Iterator[Grupo],
    crear_pool: Callable[[int], ProcessPoolExecutor],
    procesos: int,
    cuarentena: DestinoCuarentena,
    funcion_trabajo: FuncionTrabajo = procesar_grupo_en_trabajador,
    metricas: MetricasDespacho | None = None,
    detener: threading.Event | None = None,
    registro_de_pool: RegistroDePool | None = None,
) -> tuple[list[dict[str, object]], int, int]:
    """Despacha `grupos` a un `ProcessPoolExecutor`, con recuperación ante un hijo
    muerto y sin materializar la partición completa en memoria. Ventana deslizante, no
    `executor.map`: hasta `procesos` grupos en vuelo, `grupos` consumido de a uno
    (nunca `list(grupos)`, sería el problema de RAM que el iterador perezoso evita).

    Cuando un hijo muere, el pool ENTERO queda inutilizable -- `BrokenProcessPool` marca
    TODOS los futuros pendientes, no sólo el de la tarea que lo disparó. Se reprocesa en
    AISLAMIENTO ese grupo y cualquier colateral que seguía en vuelo; reencolar es seguro
    porque `Estudio.clave_documento` (restricción única) evita duplicar el mismo documento.

    Si un grupo agota sus reintentos en aislamiento, se da por perdido y se registra en
    `cuarentena` (necesario para que `residuo` del embudo cierre, ya que `entraron` lo
    cuenta desde el inventario); la corrida sigue con los demás grupos.

    Devuelve `(resultados, total_documentos, total_grupos)`, misma forma que el bucle
    secuencial.
    """
    return _EstadoDespacho(
        corrida_id=corrida_id,
        grupos=grupos,
        crear_pool=crear_pool,
        procesos=procesos,
        cuarentena=cuarentena,
        funcion_trabajo=funcion_trabajo,
        metricas=metricas if metricas is not None else MetricasDespacho(),
        detener=detener,
        registro_de_pool=registro_de_pool,
    ).ejecutar()
