"""Despacho multiproceso de grupos (openspec `paralelismo-de-procesamiento` PR 3).

Módulo real e importable (no vive en `scripts/procesar_carpeta.py`) a propósito,
por dos razones:

1. **`ProcessPoolExecutor` con `spawn` (default en Windows, verificado con
   `multiprocessing.get_start_method()`) pickla por REFERENCIA de módulo**:
   `initializer`/la función sometida a `submit()` viajan como
   `(nombre_de_modulo, nombre_calificado)`, y el hijo los resuelve con
   `import_module(nombre_de_modulo)`. Verificado empíricamente durante esta
   sesión: una función definida en un módulo cargado dinámicamente vía
   `importlib.util.spec_from_file_location` (como hace
   `tests/scripts/test_procesar_carpeta.py::_cargar_script`, porque
   `scripts/` no es un paquete instalado) **no es picklable** para un hijo
   `spawn` -- el hijo no puede resolver ese nombre de módulo sintético
   (`ModuleNotFoundError`), y el intento de todos modos **rompe el pool
   entero** (`BrokenProcessPool`), no solo esa tarea. Poniendo el
   `initializer`/la tarea acá, en un módulo real de `anonimizacion`
   (resoluble por cualquier proceso que tenga `src/` en `sys.path` -- lo que
   ya hace `tests/conftest.py` en tiempo de ejecución, y esa modificación de
   `sys.path` SÍ la hereda un hijo `spawn`, también verificado empíricamente),
   `scripts/procesar_carpeta.py` puede seguir cargándose por ruta en los
   tests existentes sin que la parte de multiproceso se rompa.
2. **Diseño pensando en el despachador futuro** (`proposal.md`, "Fuera de
   alcance... pero diseñá pensando en que va a venir"): un proceso servidor
   (el despachador desde la web, tramo siguiente) necesita invocar esta
   lógica igual que `scripts/procesar_carpeta.py`, no un script de línea de
   comandos. Un módulo de `anonimizacion.trabajadores` con una función
   (`despachar_en_paralelo`) es reusable desde ambos; lógica enterrada en
   `scripts/*.py` no lo sería.

Todo lo que cruza el límite de proceso (funciones sometidas a
`ProcessPoolExecutor.submit`/`initializer`) vive acá, a nivel de MÓDULO
(nunca closures/lambdas: tampoco son picklables). `scripts/procesar_carpeta.py`
sigue siendo el único llamador de producción (regla del proposal: "ninguna
función nueva se mergea sin llamador de producción en el mismo commit") --
este módulo es la implementación que ese llamador invoca.
"""

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

# --- Grado de concurrencia: razonamiento medido, no un número mágico -------
#
# Decisión 2 del proposal: "Default N = núcleos físicos, configurable, tope
# duro en 2 × núcleos. Se mide antes de subirlo." Esta sesión midió lo que el
# proposal marcaba como pendiente ("el techo real puede ser la memoria, no
# los núcleos"):
#
#   - Máquina de referencia de esta sesión: 6 núcleos físicos / 12 lógicos
#     (verificado con `wmic cpu get NumberOfCores,NumberOfLogicalProcessors`
#     -- no hay `psutil` ni `wmi` instalados en el entorno, ver más abajo por
#     qué no se agregan como dependencia nueva).
#   - `MotorPii()` (spaCy `es_core_news_lg` + Presidio) consume **~875 MB de
#     RSS por proceso**, medido con `K32GetProcessMemoryInfo` (ctypes,
#     sin dependencias nuevas) antes/después de instanciar, más un
#     `detectar()` real para confirmar que Presidio no reserva más al primer
#     uso. Con 6 copias (núcleos físicos de esta máquina) eso son ~5,25 GB
#     SOLO en modelos, sin contar el proceso padre, Postgres, el SO ni el
#     resto del pipeline -- en una máquina de 16 GB con otros programas
#     corriendo (el caso típico, no un servidor dedicado), el margen es
#     angosto.
#
# Por eso el default NO es "núcleos físicos" a secas: es
# `min(heurística_de_núcleos_físicos, tope_conservador_fijo)`.
#
# `heurística_de_núcleos_físicos = os.cpu_count() // 2`: asume 2 hilos por
# núcleo (SMT/Hyperthreading), que es lo que dio exactamente 6 en la máquina
# de referencia (12 lógicos verificados). No hay forma portable de leer
# núcleos FÍSICOS reales sin una dependencia nueva (`psutil`) -- a
# diferencia de Celery+Redis (que el proposal rechaza por requerir operar un
# servicio), `psutil` no tiene superficie operativa ni de PII, pero se
# prefiere NO agregarla para esto: en una máquina SIN SMT esta heurística
# SUBESTIMA los núcleos físicos, que es conservador en la dirección segura
# (menos paralelismo que el máximo posible), no un error de dirección
# peligrosa.
#
# `_TOPE_DEFAULT_CONSERVADOR = 4`: fijo, no calculado contra la RAM libre
# real en el momento de arrancar -- leer RAM disponible de forma confiable y
# portable (Windows y Linux) exige o bien `psutil`, o bien código
# específico por plataforma (`GlobalMemoryStatusEx` en Windows, `/proc/
# meminfo` en Linux) que agrega superficie de mantenimiento para un número
# que de todos modos hay que poder overridear a mano (`--procesos`) porque
# depende de qué más corre en la máquina en ese momento. 4 procesos son
# ~3,5 GB de modelos: cómodo incluso en una máquina de 8 GB con el resto del
# pipeline y el SO activos, y coincide con el N=4 que ya se mide en el banco
# de carga (`tests/carga/ejecutar_corpus.py`) -- mismo número en la
# justificación y en la medición, no una coincidencia.
_TOPE_DEFAULT_CONSERVADOR = 4
# Tope duro (proposal, Decisión 2): pasado N=núcleos, cada proceso extra solo
# compra latencia de red (el término de CPU del modelo de speedup deja de
# mejorar), y cuesta una copia más de ~875 MB en RAM. 2x núcleos LÓGICOS
# (no físicos) es deliberadamente más permisivo que el default: es un techo
# de seguridad para quien mide su propia máquina y decide subir el número a
# mano, no una recomendación.
_MULTIPLICADOR_TOPE_DURO = 2
# ALTO 4 de revisión adversarial: validar SOLO contra 2x núcleos lógicos
# ignora el recurso que este mismo módulo argumenta que es el techo real --
# la memoria. En la máquina de referencia (12 lógicos) eso dejaba pasar
# `--procesos 24` sin ningún rechazo: ~21 GB solo en copias de
# `es_core_news_lg`, muy por encima del margen que el propio docstring de
# arriba llama "angosto". El tope duro real es el MÁS CHICO entre los dos
# recursos: núcleos lógicos y memoria.
#
# `_MEMORIA_ESTIMADA_POR_PROCESO_MB`/`_PRESUPUESTO_MEMORIA_TOPE_DURO_MB` son
# constantes fijas, no una lectura de RAM libre real (misma razón que
# `_TOPE_DEFAULT_CONSERVADOR`: leer RAM disponible de forma confiable y
# portable exige `psutil` o código específico por plataforma, y ese número
# de todos modos hay que poder overridearlo a mano conociendo la máquina
# real). El presupuesto del TOPE DURO (8 GiB) es deliberadamente más
# generoso que el del DEFAULT (~3,5 GB con `_TOPE_DEFAULT_CONSERVADOR=4`):
# el default tiene que ser seguro sin que nadie mida nada, el tope duro sólo
# tiene que evitar el caso claramente absurdo (`--procesos` a mano en una
# máquina que el operador conoce, sin llegar a poder pedir 21 GB).
#
# LIMITACIÓN CONOCIDA, ACEPTADA, NO RESUELTA ACÁ (revisión adversarial,
# hallazgo no bloqueante): `_PRESUPUESTO_MEMORIA_TOPE_DURO_MB` es fijo para
# TODAS las máquinas -- una con 4 GB de RAM y 16 núcleos lógicos obtiene el
# MISMO tope (9) que una con 64 GB, así que `--procesos 9` en la máquina
# chica pide ~7,9 GB solo en modelos sin que este módulo lo detecte ni lo
# impida. Leer la RAM real de la máquina es una decisión aparte (implica
# `psutil` o código específico por sistema operativo, ver arriba) que este
# cambio no toma. Quien pasa `--procesos` a mano por encima del default es
# responsable de conocer la memoria real de SU máquina -- el tope duro
# protege contra el caso absurdo (`--procesos 24`), no contra cualquier
# combinación de hardware chico y `--procesos` grande dentro del tope.
_MEMORIA_ESTIMADA_POR_PROCESO_MB = 875
_PRESUPUESTO_MEMORIA_TOPE_DURO_MB = 8192
# Reintentos EN AISLAMIENTO por grupo ante `BrokenProcessPool` antes de
# darlo por perdido (ver `_reprocesar_en_aislamiento`). El intento en el
# pool PRINCIPAL nunca cuenta acá -- solo cuentan los reintentos que
# `_reprocesar_en_aislamiento` hace por su cuenta, uno a la vez. Con el
# default (1): 1 intento en el pool principal (gratis) + hasta 1 reintento
# en aislamiento = 2 cargas completas de proceso+modelo antes de dar un
# grupo tóxico por perdido, no 3 (revisión adversarial: medido con un
# contador real en disco, la comparación `>` en vez de `>=` daba 3 -- ver
# `_reprocesar_en_aislamiento`). No infinito: un grupo cuyo contenido causa
# la muerte del proceso de forma determinística (p. ej. un PDF que dispara
# un bug real de memoria en PyMuPDF/spaCy) moriría por siempre si se
# reintentara sin límite, colgando la corrida entera a pesar de que el
# objetivo de este módulo es JUSTO que un hijo muerto no la cuelgue.
MAX_REINTENTOS_POR_GRUPO = 1


def grado_de_concurrencia_por_defecto() -> int:
    """Default conservador de `--procesos` -- ver el razonamiento medido arriba."""
    logicos = os.cpu_count() or 2
    return max(1, min(logicos // 2, _TOPE_DEFAULT_CONSERVADOR))


def tope_duro_concurrencia() -> int:
    """El más chico entre 2x núcleos lógicos y el presupuesto de memoria
    (`_PRESUPUESTO_MEMORIA_TOPE_DURO_MB` // `_MEMORIA_ESTIMADA_POR_PROCESO_MB`)
    -- ver el razonamiento medido arriba (ALTO 4, revisión adversarial: antes
    de este ajuste solo se validaba contra núcleos, dejando pasar valores que
    exceden por mucho el recurso que este módulo mismo llama el techo real."""
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
    """`initializer` de `ProcessPoolExecutor`: corre UNA vez por proceso hijo,
    antes de la primera tarea. Construye acá -- no en el padre -- todo lo que
    no es picklable o es demasiado caro para viajar por la cola de tareas:
    `MotorPii` (spaCy, ~875 MB medidos), el `Engine` de Postgres (una conexión
    de socket no sobrevive un pickle) y el pepper.

    El pepper NO se recibe como parámetro. `obtener_pepper()` lo lee de
    `ANONIMIZACION_PEPPER`/`ANONIMIZACION_PEPPER_ARCHIVO`. Verificado
    empíricamente en esta sesión (con `spawn`, el método de arranque default
    en Windows): un valor asignado a `os.environ` EN RUNTIME en el proceso
    padre -- no antes de arrancar python, no vía shell -- SÍ llega al
    entorno del hijo, y `obtener_pepper()` en el hijo usa su PROPIO
    `lru_cache` (un proceso distinto, nunca comparte el cache del padre). El
    pepper nunca toca disco (salvo que la fuente configurada sea
    `ANONIMIZACION_PEPPER_ARCHIVO`, y en ese caso cada hijo lee el mismo
    archivo local que leería el padre, no un intermediario nuevo) ni pasa
    por ningún broker -- exactamente el argumento del proposal para
    descartar Celery+Redis (Decisión 1: "los hijos heredan `os.environ`").
    Pasarlo como argumento de `initializer` lo haría viajar pickleado por el
    mismo canal que cualquier otro dato, una copia más del secreto en
    tránsito sin necesidad: la herencia de entorno ya lo resuelve.

    No llama `Base.metadata.create_all`: el padre ya lo hizo contra la MISMA
    base antes de arrancar el pool (`scripts/procesar_carpeta.py::ejecutar`),
    y el esquema es una propiedad de la base, no de la conexión -- repetirlo
    acá sería una consulta de metadata redundante por hijo.

    `directorio_marcador_pid` (`None` = producción, mismo convenio que
    `dormir`/`resolver_claves` en `tareas.construir_fabrica_ejecutor`): punto
    de instrumentación para el test de paralelismo real -- si se pasa, cada
    hijo deja un archivo vacío nombrado con su propio PID. Sirve para que un
    test confirme, sin simular nada, que dos grupos terminaron en procesos
    del sistema operativo genuinamente distintos.
    """
    pepper = obtener_pepper()
    motor = MotorPii()
    engine = construir_engine_postgres(db_url)
    destino = EscritorPostgres(engine)
    cuarentena = EscritorCuarentena(engine)
    resolutor = ResolutorClavesPostgres(destino)

    # Import diferido: evita un ciclo de import a nivel de módulo con
    # `trabajadores.tareas` (que a su vez podría importar este módulo en el
    # futuro despachador web -- ver docstring del módulo).
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
    """Función de MÓDULO (picklable) que un hijo ya inicializado ejecuta por
    grupo. Delega en `tareas.procesar_grupo` -- la MISMA tarea Celery real
    que ya invoca `scripts/procesar_carpeta.py` en el camino secuencial, sin
    reimplementar nada del procesamiento en sí. Un closure/lambda acá NO
    funcionaría: pickle no puede serializarlos."""
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
    """Fábrica de producción de `ProcessPoolExecutor` -- un `initializer` por
    hijo, nunca un motor/engine compartido entre procesos."""
    return ProcessPoolExecutor(
        max_workers=procesos,
        initializer=inicializar_trabajador,
        initargs=(entrada, db_url, tope_bytes, directorio_marcador_pid),
    )


def _error_grupo_perdido(referencia: Referencia, corrida_id: str) -> ErrorDocumento:
    """`ErrorDocumento` de un documento cuyo grupo se dio por perdido tras
    agotar `MAX_REINTENTOS_POR_GRUPO` (ver `despachar_en_paralelo`). Se
    construye UNA vez y se usa tanto para `cuarentena.registrar` (persiste el
    apartado, necesario para el invariante del embudo) como para el
    `resumen_trazable()` que viaja en `resultados` -- las dos superficies
    deben describir exactamente el mismo fallo.

    `codigo=PROCESO_INTERRUMPIDO` (revisión adversarial, ALTO 3), NO
    `ERROR_TRANSITORIO_AGOTADO`: ese código ya significa "un error de
    IO/conexión DENTRO del pipeline, sobre un documento que sí llegó a
    ejecutarse" -- reusarlo acá volvía indistinguible, para quien opera la
    corrida, un problema real del documento de uno del PROCESO que lo
    procesaba (memoria, infra). `etapa=EtapaDocumento.DESPACHO` (tampoco un
    string libre, revisión adversarial): un string fuera de `ETAPAS_EMBUDO`
    se sumaba al total global del embudo pero desaparecía del desglose por
    etapa sin que nada lo señalara -- ver `web/embudo_corrida.py`.
    """
    return ErrorDocumento(
        id_documento=referencia["id_documento"],
        etapa=EtapaDocumento.DESPACHO,
        codigo=CodigoErrorDocumento.PROCESO_INTERRUMPIDO,
        corrida_id=corrida_id,
    )


@dataclass
class MetricasDespacho:
    """Contadores de eventos de RECUPERACIÓN del despachador -- ni documentos
    ni etapas del pipeline (eso ya lo cubre
    `observabilidad/metricas.py::ColectorMetricas`, con su propio vocabulario
    de `Etapa`/`CodigoErrorDocumento`, y vive por proceso HIJO, no en el
    padre; los eventos de acá son de la capa de orquestación de procesos, en
    el padre, y no tienen equivalente ahí).

    ALTO 1 de revisión adversarial: la recuperación tiene un costo real en
    recargas completas de `MotorPii` (~875 MB medidos cada una) que antes no
    se veía en ningún lado -- medido por el auditor: con solo 3 crashes y
    `procesos=4` sobre 48 grupos aparecieron 25 PIDs de hijos distintos,
    contra los 4 del estado estable (~21 recargas extra). Sin un contador,
    un operador con una corrida de horas no tenía forma de saber que estaba
    pagando una tormenta de recargas -- ver el docstring de
    `despachar_en_paralelo`, sección "Costo real de la recuperación", para
    la explicación completa de por qué el costo es tan alto.

    Mismo patrón que `MetricasEnMemoria`: contadores simples, expuestos vía
    `snapshot()`, sin lock -- a diferencia de `MetricasEnMemoria` (que
    corre en un worker de Celery con tareas concurrentes en el mismo
    proceso), `_EstadoDespacho` es de un solo hilo en el proceso PADRE, así
    que no hace falta sincronización.
    """

    recreaciones_de_pool_principal: int = 0
    reprocesos_en_aislamiento: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "recreaciones_de_pool_principal": self.recreaciones_de_pool_principal,
            "reprocesos_en_aislamiento": self.reprocesos_en_aislamiento,
        }


@dataclass
class RegistroDePool:
    """Referencia al `ProcessPoolExecutor` ACTUALMENTE activo de un despacho
    en curso -- revisión adversarial ronda 3, hallazgo 3: "el resguardo del
    timeout es una ilusión".

    Por qué hace falta: `detener` (el `threading.Event` de `despachar_en_paralelo`)
    sólo evita tomar grupos NUEVOS -- no interrumpe un worker que YA está
    ocupado (cargando `MotorPii`, procesando un documento). Medido: con
    `timeout=0,2` en el apagado cooperativo, el proceso quedó colgado ~114 s
    de todos modos, porque el `atexit` de `concurrent.futures.process` espera
    a que el pool ACTIVO termine, sin importar qué tan cooperativo haya sido
    el pedido de detener. Un apagado con un límite de tiempo REAL exige poder
    terminar los workers a la fuerza cuando el cooperativo se agota --
    `ProcessPoolExecutor` no expone ninguna API pública para eso, así que
    quien quiera hacerlo necesita una referencia al pool mientras está vivo.

    Mutado en el lugar (nunca reasignado, mismo convenio que `MetricasDespacho`):
    `_EstadoDespacho.ejecutar()` actualiza `self.pool` cada vez que crea o
    recrea el pool principal (arranque y tras un `BrokenProcessPool`) --
    quien tiene esta instancia ve siempre el pool VIGENTE, sin necesitar que
    `despachar_en_paralelo` termine para consultarlo.

    `terminar_a_la_fuerza` usa `ProcessPoolExecutor._processes` -- API
    PRIVADA de `concurrent.futures.process`, no hay ninguna pública para
    "matar los workers ya". Es un último recurso deliberado, documentado
    como frágil: si una versión futura de CPython cambia ese atributo
    interno, esta función deja de encontrar procesos para terminar (falla en
    silencio, no lanza) en vez de romper con un `AttributeError` -- ver el
    cuerpo del método.
    """

    pool: ProcessPoolExecutor | None = None

    def terminar_a_la_fuerza(self) -> int:
        """Manda una señal de terminación (SIGTERM en Unix,
        `TerminateProcess` en Windows vía `multiprocessing.Process.terminate`)
        a cada proceso hijo VIVO del pool actual -- sin esperar un cierre
        limpio. El trabajo en vuelo en esos procesos se pierde: ningún
        documento a medio procesar en el momento de la terminación llega a
        escribirse. Devuelve la cantidad de procesos a los que se les mandó
        la señal (no espera a que mueran -- eso lo confirma el llamador
        observando que el hilo de despacho termina).

        Best-effort ante la fragilidad del acceso privado: si `pool` no
        expone `_processes` (cambio interno de una versión futura de
        `concurrent.futures`), devuelve 0 en vez de lanzar -- un apagado que
        no logra terminar procesos no puede además tumbar al llamador con
        una excepción por una API que nunca estuvo garantizada.
        """
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
    """Estado mutable de una corrida de `despachar_en_paralelo`, en su propia
    clase (no closures anidadas dentro de la función) para que cada método
    tenga su propio presupuesto de complejidad ciclomática (`ruff`/`C901`)
    en vez de acumularse todo sobre una única función -- ver el docstring de
    `despachar_en_paralelo` para el razonamiento completo del algoritmo;
    esta clase es solo su implementación."""

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
        # Revisión adversarial crítico 2: si se pidió detener (Ctrl+C en el
        # servidor), NO se toma ningún grupo NUEVO del iterador -- ni en la
        # ventana inicial ni al reponer un hueco que dejó un grupo terminado.
        # Lo que ya estaba en vuelo se deja terminar normalmente (drena solo,
        # el `while self.en_vuelo:` de `ejecutar()` sale cuando no queda
        # nada pendiente). Esto acota el tiempo de apagado al de los grupos
        # YA en curso -- segundos a bajas decenas de segundos por grupo, no
        # las horas que dura la corrida completa.
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
        # MEDIO 5 de revisión adversarial: sin este `pop`, `intentos_por_grupo`
        # crece sin límite durante toda la corrida (nunca se borra una
        # entrada) -- sobre ~100.000 grupos son cientos de miles de enteros
        # acumulados en el padre para grupos que ya terminaron y nunca se
        # van a volver a consultar.
        self.intentos_por_grupo.pop(indice, None)

    def _aceptar_exito(self, indice: int, grupo: Grupo, parcial: list[dict[str, object]]) -> None:
        self.resultados.extend(parcial)
        self.total_documentos += len(grupo)
        self.total_grupos += 1
        self.intentos_por_grupo.pop(indice, None)

    def _reprocesar_en_aislamiento(self, indice: int, grupo: Grupo) -> None:
        """Reprocesa un grupo SOLO, en su propio pool de UN worker -- la
        única forma de atribuir causalmente un crash cuando varios grupos
        compartían el pool que se rompió.

        CRÍTICO 2 de revisión adversarial: `concurrent.futures._base.wait`
        convierte la lista de futuros a un `set` antes de esperarlos --
        cuál de ellos "sale primero" del `for futuro in terminados` es
        orden de HASH, no de causalidad. Tratar al primero que itera como
        "el culpable" (versión anterior de este método) manda estudios
        clínicos SANOS a cuarentena por compartir pool con uno tóxico: la
        revisión lo reprodujo, con `procesos=4` y un solo grupo malo, 2 de
        3 grupos perdidos eran sanos.

        No hay API pública de `ProcessPoolExecutor` para preguntar "¿qué
        `work item` corría en el proceso que murió?" -- así que en vez de
        adivinar, se re-somete el grupo SOLO: si vuelve a morir sin
        hermanos con quien compartir pool, es indiscutiblemente su propia
        culpa (recién ahí carga su cupo de reintentos). Si NO muere en
        aislamiento, nunca fue culpable -- su resultado se acepta
        normalmente y su contador de reintentos NUNCA se toca, sin
        importar cuántas veces haya sido baja colateral de otro.

        Costo aceptado y explícito: procesar en aislamiento es
        SECUENCIAL, un grupo a la vez -- durante la recuperación de un
        pool roto se pierde concurrencia temporalmente. Es el precio de
        la atribución causal correcta; los crashes deberían ser raros
        (`MAX_REINTENTOS_POR_GRUPO` sigue acotando cuánto puede alargarse
        esto por grupo).
        """
        self.metricas.reprocesos_en_aislamiento += 1
        pool_aislado = self.crear_pool(1)
        futuro = pool_aislado.submit(self.funcion_trabajo, self.corrida_id, grupo)
        try:
            parcial = futuro.result()
        except BrokenProcessPool:
            pool_aislado.shutdown(wait=False, cancel_futures=True)
            self.intentos_por_grupo[indice] = self.intentos_por_grupo.get(indice, 0) + 1
            # `>=`, no `>` (revisión adversarial): con `>` el intento en el
            # pool principal quedaba "gratis" y encima se permitían 2
            # reintentos en aislamiento -- 3 cargas de proceso+modelo en
            # total para un grupo tóxico, contradiciendo el comentario de
            # `MAX_REINTENTOS_POR_GRUPO` ("1 reintento"). Con `>=`, 1
            # reintento en aislamiento alcanza su cupo tras UN solo intento
            # extra -- 2 cargas en total, lo que el nombre siempre dijo.
            if self.intentos_por_grupo[indice] >= MAX_REINTENTOS_POR_GRUPO:
                self._dar_por_perdido(indice, grupo)
            else:
                self._reprocesar_en_aislamiento(indice, grupo)
        else:
            pool_aislado.shutdown(wait=True)
            self._aceptar_exito(indice, grupo, parcial)

    def _asignar_pool(self, pool: ProcessPoolExecutor | None) -> None:
        """Único punto que reasigna `self.pool` -- mantiene
        `self.registro_de_pool` (si hay uno) sincronizado con el pool
        VIGENTE (revisión adversarial ronda 3, hallazgo 3: `RegistroDePool`
        necesita ver el pool real en todo momento, incluso tras una
        recreación por `BrokenProcessPool`, para poder terminarlo a la
        fuerza si el apagado cooperativo se agota)."""
        self.pool = pool
        if self.registro_de_pool is not None:
            self.registro_de_pool.pool = pool

    def _recuperar_de_pool_roto(self, indice: int, grupo: Grupo) -> None:
        """Descarta el pool roto y reprocesa en aislamiento TODO lo que
        seguía en vuelo (`afectados`: el grupo que disparó la excepción más
        cualquier `colateral` que compartía ese mismo pool) -- ver
        `_reprocesar_en_aislamiento` para la atribución causal.

        CRÍTICO 1 de revisión adversarial: termina SIEMPRE recreando el
        pool principal y reponiendo la ventana hasta su ancho completo
        (`self.procesos`). Antes de este ajuste, `_dar_por_perdido` nunca
        llamaba `_reponer()`: el lugar de un grupo perdido quedaba vacío
        para siempre, y la ventana deslizante colapsaba a un ancho menor
        por el resto de la corrida -- sin ningún log ni métrica que lo
        señalara. Sobre un corpus de horas, un solo documento problemático
        temprano degradaba el resto de la corrida a (procesos - 1) para
        siempre.

        EXCEPCIÓN a "siempre recrea" (revisión adversarial ronda 3, hallazgo
        3): si `detener` ya está seteado, un `BrokenProcessPool` acá puede
        ser la CONSECUENCIA DELIBERADA de `RegistroDePool.terminar_a_la_fuerza`
        (el apagado cooperativo se agotó y alguien terminó los workers a
        propósito) -- desde acá es indistinguible de un crash real. Recrear
        el pool y reprocesar en ese momento sería exactamente lo opuesto de
        lo que se pidió: seguiría gastando procesos nuevos justo cuando se
        pidió parar. Los afectados se dan por perdidos (misma cuarentena que
        cualquier otro grupo perdido) SIN reprocesar ni recrear -- `self.pool`
        queda en `None`, y `ejecutar()` lo tolera (no llama `shutdown` sobre
        `None`).
        """
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
            # Ya fue reencolado/dado por perdido como parte de la
            # recuperación de OTRO futuro de este mismo lote de `wait()` --
            # ver el docstring de `despachar_en_paralelo`: un pool roto marca
            # varios futuros a la vez, no de a uno.
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
                    # `_recuperar_de_pool_roto` ya resolvió TODO lo que
                    # seguía en vuelo en el pool viejo (colaterales
                    # incluidos, vía aislamiento) y ya repuso la ventana (o,
                    # si `detener` ya estaba seteado, dejó `self.pool` en
                    # `None` a propósito -- ver su docstring) -- el resto de
                    # `terminados` de este lote pertenece a ese pool
                    # descartado. Volver a `wait()` sobre el pool nuevo (o
                    # salir del `while` si no quedó ninguno) en vez de
                    # seguir iterando.
                    break

        # `self.pool` puede ser `None` acá (revisión adversarial ronda 3,
        # hallazgo 3): `_recuperar_de_pool_roto` lo deja así cuando el
        # `BrokenProcessPool` ocurre con `detener` ya seteado -- un apagado
        # a la fuerza no tiene un pool "principal" que cerrar de nuevo.
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
    """Despacha `grupos` a un `ProcessPoolExecutor`, con recuperación ante un
    hijo muerto y sin materializar la partición completa en memoria.

    `registro_de_pool` (revisión adversarial ronda 3, hallazgo 3): un
    `RegistroDePool` opcional que, si se pasa, queda apuntando SIEMPRE al
    pool VIGENTE mientras el despacho está en curso -- incluso tras una
    recreación por `BrokenProcessPool`. El LLAMADOR (fuera de este hilo)
    puede usarlo para `terminar_a_la_fuerza()` si el apagado cooperativo
    (`detener`) se agota sin que el despacho termine solo -- ver el
    docstring de `RegistroDePool` para el porqué hace falta: `detener` sólo
    evita tomar trabajo NUEVO, nunca interrumpe un worker ya ocupado.

    `detener` (revisión adversarial crítico 2, feature `despachador-desde-el-panel`):
    un `threading.Event` opcional que, una vez seteado por el LLAMADOR (desde
    otro hilo -- p. ej. `scripts/servir_panel.py::main` ante `KeyboardInterrupt`),
    hace que esta función deje de tomar grupos NUEVOS del iterador `grupos` y
    retorne apenas termine lo que ya estaba en vuelo. No cancela futuros ya
    sometidos ni mata procesos hijos a la fuerza -- `pool.shutdown(wait=True)`
    al final sigue esperando a que el pool termine limpio, sin huérfanos.
    `None` (default): comportamiento sin cambios, corre hasta agotar `grupos`.

    `metricas` (`None` = se crea una instancia descartable, mismo convenio
    que `dormir`/`resolver_claves` en `tareas.construir_fabrica_ejecutor`):
    quien llama y quiere OBSERVAR el costo de la recuperación pasa su propia
    `MetricasDespacho()` -- se muta en el lugar (nunca se reasigna), así que
    el llamador puede inspeccionarla después de que esta función retorna.
    Ver "Costo real de la recuperación" más abajo para por qué esto importa.

    `crear_pool` recibe el grado de concurrencia deseado (`int`), no un
    factory de aridad cero: la recuperación ante un pool roto necesita poder
    pedir un pool de UN solo worker para aislar causalmente un crash (ver
    `_reprocesar_en_aislamiento`), además del pool principal de `procesos`
    workers.

    **Ventana deslizante, no `executor.map`**: se mantienen en vuelo hasta
    `procesos` grupos a la vez, reponiendo el siguiente ítem del iterador
    recién cuando uno termina (`_reponer`). `grupos` se consume de a UNO
    (`next(grupos, None)`), nunca con `list(grupos)` -- el llamador (`scripts/
    procesar_carpeta.py::ejecutar`) es responsable de pasar un iterador
    perezoso real (`itertools.chain([primer_grupo], iterador_grupos)`, el
    mismo patrón que ya usa el camino secuencial), no una lista. Con el
    corpus real (~100.000 grupos), materializarla sería exactamente el
    problema de RAM que el PR 2 (`listar_grupos()` perezoso) existe para
    evitar -- este despachador no puede reintroducirlo por su cuenta.

    **`BrokenProcessPool` (hijo matado por el SO, p. ej. OOM-kill)**: cuando
    UN hijo muere de forma abrupta, el pool ENTERO queda inutilizable --no
    solo la tarea que corría en ese hijo-- y `concurrent.futures` lo señala
    marcando `BrokenProcessPool` en TODOS los futuros pendientes, los de ese
    hijo y los de cualquier otro (verificado empíricamente en esta sesión).
    Al capturarla, se descarta el pool viejo
    (`shutdown(wait=False, cancel_futures=True)`) y se reprocesa en
    AISLAMIENTO (`_reprocesar_en_aislamiento`) TANTO el grupo que disparó la
    excepción COMO cualquier otro grupo que seguía en vuelo en el pool roto
    (`afectados`). Reencolar es SEGURO por idempotencia, no una suposición:
    `EscritorPostgres.escribir_registro`/`escribir_episodio`
    (`salida/destinos/postgres.py`) y `EscritorCuarentena.registrar`
    (`salida/cuarentena.py`) ya toleran reprocesar el mismo documento -- un
    grupo cuyos primeros documentos ya se habían escrito antes de que su
    hijo muriera simplemente los vuelve a encontrar como "ya escritos" y no
    los duplica.

    **Atribución causal del crash, no un culpable arbitrario** (revisión
    adversarial, hallazgo crítico: `concurrent.futures._base.wait` convierte
    la lista de futuros a un `set` -- qué futuro "sale primero" del bucle es
    orden de HASH, no de causalidad; tratar al primero como culpable
    reproducidamente mandaba estudios SANOS a cuarentena por compartir pool
    con uno tóxico). Por eso cada `afectado` se reprocesa SOLO, en su propio
    pool de un worker: si vuelve a morir sin hermanos con quien compartir
    pool, es indiscutiblemente su propia culpa y recién ahí carga su cupo de
    reintentos; si no muere en aislamiento, nunca fue culpable, se acepta su
    resultado y su contador de reintentos nunca se toca. Ver
    `_reprocesar_en_aislamiento` para el detalle.

    **Costo real de la recuperación -- alto, y antes invisible** (revisión
    adversarial, hallazgo no bloqueante): recuperarse de UN `BrokenProcessPool`
    es mucho más caro que "reintentar la tarea". Dos causas se suman:

    1. Recrear el pool principal apaga TODOS sus workers, incluidos los
       sanos que seguían vivos -- no solo el que murió.
    2. Cada `afectado` (el culpable Y cualquier colateral sano) se
       reprocesa en su PROPIO pool de un worker, con su PROPIA carga
       completa de `MotorPii` (~875 MB, ~2-3 s medidos) -- nunca reusa un
       proceso ya inicializado.

    Medido por el auditor: con solo 3 crashes y `procesos=4` sobre 48
    grupos, aparecieron **25 PIDs de hijos distintos**, contra los 4 del
    estado estable -- ~21 recargas completas del modelo de más por 3
    crashes. Sobre un corpus de horas, un patrón de crashes repetido podría
    comerse buena parte de la ganancia de este tramo sin que nadie lo note
    si nadie mide esto. Por eso `MetricasDespacho` (`recreaciones_de_pool_principal`,
    `reprocesos_en_aislamiento`) existe: sin un contador expuesto, un
    operador con una corrida larga no tiene forma de saber que está pagando
    una tormenta de recargas. `scripts/procesar_carpeta.py` reporta estos
    contadores al terminar la corrida.

    **Reposición de la ventana tras una pérdida** (revisión adversarial,
    hallazgo crítico): `_recuperar_de_pool_roto` SIEMPRE termina recreando
    el pool principal y reponiendo la ventana hasta `procesos` -- antes de
    este ajuste, un grupo dado por perdido dejaba su lugar vacío para
    siempre (`_dar_por_perdido` nunca llamaba `_reponer()`), y la ventana
    deslizante colapsaba a un ancho menor por el resto de la corrida, sin
    ningún log ni métrica que lo señalara. Sobre un corpus de horas, un solo
    documento problemático temprano degradaba el resto de la corrida a
    concurrencia reducida para siempre.

    **Tope de reintentos (`MAX_REINTENTOS_POR_GRUPO`)**: si un grupo agota
    sus reintentos EN AISLAMIENTO (su propio contenido dispara la muerte del
    proceso de forma determinística, no comparte la culpa con nadie más), se
    da por perdido: se registra en `cuarentena` un `ErrorDocumento` por cada
    referencia del grupo (`_dar_por_perdido`/`_error_grupo_perdido`,
    `codigo=PROCESO_INTERRUMPIDO`, `etapa=DESPACHO` -- distintos de un fallo
    real del pipeline, revisión adversarial ALTO 3) y la corrida SIGUE con
    los demás grupos -- nunca propaga la excepción hacia arriba. Registrar
    en `cuarentena` (no solo devolver un resultado en memoria) es necesario
    para el invariante del embudo (`web/embudo_corrida.py`,
    `residuo = entraron - (publicados + apartados)`): `entraron` ya cuenta
    estos documentos desde el inventario (un solo proceso, PR 2), así que si
    se los diera por perdidos SIN apartarlos, `residuo` quedaría positivo
    para siempre -- un embudo que nunca cierra, indistinguible de documentos
    perdidos de verdad.

    Devuelve `(resultados, total_documentos, total_grupos)` -- misma forma
    que el bucle secuencial de `scripts/procesar_carpeta.py::ejecutar`, para
    que el llamador pueda tratar ambos caminos igual después de despachar.
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
