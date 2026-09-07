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
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento
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
# Reintentos por grupo ante `BrokenProcessPool` antes de darlo por perdido
# (ver `despachar_en_paralelo`). 1 reintento, no infinito: un grupo cuyo
# contenido causa la muerte del proceso de forma determinística (p. ej. un
# PDF que dispara un bug real de memoria en PyMuPDF/spaCy) moriría por
# siempre si se reintentara sin límite, colgando la corrida entera a pesar
# de que el objetivo de este módulo es JUSTO que un hijo muerto no la
# cuelgue.
MAX_REINTENTOS_POR_GRUPO = 1


def grado_de_concurrencia_por_defecto() -> int:
    """Default conservador de `--procesos` -- ver el razonamiento medido arriba."""
    logicos = os.cpu_count() or 2
    return max(1, min(logicos // 2, _TOPE_DEFAULT_CONSERVADOR))


def tope_duro_concurrencia() -> int:
    """2x núcleos lógicos -- ver el razonamiento medido arriba."""
    return _MULTIPLICADOR_TOPE_DURO * (os.cpu_count() or 1)


def validar_grado_concurrencia(procesos: int) -> int:
    """Valida `--procesos`; lanza `ValueError` fuera de [1, tope_duro]."""
    if procesos < 1:
        raise ValueError("procesos debe ser al menos 1")
    tope = tope_duro_concurrencia()
    if procesos > tope:
        raise ValueError(
            f"procesos={procesos} supera el tope duro de 2x nucleos logicos "
            f"({tope} en esta maquina). Pasado ese punto cada proceso extra solo "
            "compra latencia de red (el termino de CPU del modelo de speedup deja "
            "de mejorar) y cuesta una copia mas de es_core_news_lg en RAM "
            "(~875 MB medidos, ver docstring de grado_de_concurrencia_por_defecto) "
            "-- medir el pico de memoria real antes de subirlo."
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

    Reutiliza `CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO` en vez de un
    código nuevo: semánticamente es el mismo caso que ya cubre ese código
    ("se agotaron los reintentos de un error transitorio -- reprocesar más
    tarde puede tener éxito", `dominio/errores.py`) -- un hijo muerto por el
    sistema operativo (p. ej. OOM-kill) es transitorio de la misma forma que
    un error de IO/conexión: no es un defecto determinístico del documento.
    `etapa` es un string libre (`ErrorDocumento.etapa: str | EtapaDocumento`
    lo permite) porque esto ocurre POR ENCIMA del pipeline -- en la capa de
    gestión de procesos, no en ninguna de las etapas que ya modela
    `EtapaDocumento` -- y forzarlo a una de esas etiquetas sería impreciso.
    """
    return ErrorDocumento(
        id_documento=referencia["id_documento"],
        etapa="despacho_paralelo",
        codigo=CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO,
        corrida_id=corrida_id,
    )


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
    crear_pool: Callable[[], ProcessPoolExecutor]
    procesos: int
    cuarentena: DestinoCuarentena
    funcion_trabajo: FuncionTrabajo

    resultados: list[dict[str, object]] = field(default_factory=list)
    total_documentos: int = 0
    total_grupos: int = 0
    contador_indices: Iterator[int] = field(default_factory=itertools.count)
    intentos_por_grupo: dict[int, int] = field(default_factory=dict)
    en_vuelo: dict[Future[list[dict[str, object]]], tuple[int, Grupo]] = field(default_factory=dict)
    pool: ProcessPoolExecutor | None = None

    def _reponer(self) -> None:
        grupo = next(self.grupos, None)
        if grupo is None:
            return
        indice = next(self.contador_indices)
        self.intentos_por_grupo[indice] = 0
        futuro = self.pool.submit(self.funcion_trabajo, self.corrida_id, grupo)
        self.en_vuelo[futuro] = (indice, grupo)

    def _dar_por_perdido(self, grupo: Grupo) -> None:
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

    def _recuperar_de_pool_roto(self, indice: int, grupo: Grupo) -> None:
        """Descarta el pool roto, crea uno nuevo y reencola el trabajo
        pendiente. Solo `indice`/`grupo` (el futuro que disparó la excepción)
        carga su cupo de reintentos -- ver el docstring de
        `despachar_en_paralelo` para el porqué de esa asimetría."""
        colaterales = list(self.en_vuelo.values())
        self.en_vuelo.clear()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.pool = self.crear_pool()

        self.intentos_por_grupo[indice] += 1
        if self.intentos_por_grupo[indice] > MAX_REINTENTOS_POR_GRUPO:
            self._dar_por_perdido(grupo)
        else:
            futuro_nuevo = self.pool.submit(self.funcion_trabajo, self.corrida_id, grupo)
            self.en_vuelo[futuro_nuevo] = (indice, grupo)

        for indice_colateral, grupo_colateral in colaterales:
            futuro_nuevo = self.pool.submit(self.funcion_trabajo, self.corrida_id, grupo_colateral)
            self.en_vuelo[futuro_nuevo] = (indice_colateral, grupo_colateral)

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
            self.resultados.extend(parcial)
            self.total_documentos += len(grupo)
            self.total_grupos += 1
            self._reponer()

    def ejecutar(self) -> tuple[list[dict[str, object]], int, int]:
        self.pool = self.crear_pool()
        for _ in range(self.procesos):
            self._reponer()

        while self.en_vuelo:
            terminados, _ = wait(list(self.en_vuelo.keys()), return_when=FIRST_COMPLETED)
            pool_antes = self.pool
            for futuro in terminados:
                self._procesar_terminado(futuro)
                if self.pool is not pool_antes:
                    # `_recuperar_de_pool_roto` ya reencoló TODO lo que
                    # seguía en vuelo en el pool viejo (colaterales
                    # incluidos) -- el resto de `terminados` de este lote
                    # pertenece a ese pool descartado. Volver a `wait()`
                    # sobre el pool nuevo en vez de seguir iterando.
                    break

        self.pool.shutdown(wait=True)
        return self.resultados, self.total_documentos, self.total_grupos


def despachar_en_paralelo(
    *,
    corrida_id: str,
    grupos: Iterator[Grupo],
    crear_pool: Callable[[], ProcessPoolExecutor],
    procesos: int,
    cuarentena: DestinoCuarentena,
    funcion_trabajo: FuncionTrabajo = procesar_grupo_en_trabajador,
) -> tuple[list[dict[str, object]], int, int]:
    """Despacha `grupos` a un `ProcessPoolExecutor`, con recuperación ante un
    hijo muerto y sin materializar la partición completa en memoria.

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
    hijo y los de cualquier otro (verificado empíricamente en esta sesión:
    ver `scratchpad` de la sesión de implementación). Por eso, al capturar
    `BrokenProcessPool`, se descarta el pool viejo
    (`shutdown(wait=False, cancel_futures=True)`), se crea uno nuevo, y se
    reencolan TANTO el grupo que disparó la excepción COMO cualquier otro
    grupo que seguía en vuelo en el pool roto (`colaterales`). Esto es SEGURO
    por idempotencia, no una suposición: `EscritorPostgres.escribir_registro`/
    `escribir_episodio` (`salida/destinos/postgres.py`) y
    `EscritorCuarentena.registrar` (`salida/cuarentena.py`) ya toleran
    reprocesar el mismo documento -- un grupo cuyos primeros documentos ya
    se habían escrito antes de que su hijo muriera simplemente los vuelve a
    encontrar como "ya escritos" y no los duplica.

    **Solo el grupo que disparó la excepción carga su cupo de reintentos**;
    los `colaterales` se reencolan gratis, sin tocar su contador. Hallazgo
    real de esta sesión (reproducido con un test que hacía morir DOS grupos
    a la vez con `procesos=2`, antes de este ajuste): cobrarle un reintento a
    TODO lo que estaba en vuelo -- incluidos grupos que ni siquiera habían
    llegado a arrancar en un worker todavía, porque `ProcessPoolExecutor`
    tarda en levantar cada proceso -- agotaba `MAX_REINTENTOS_POR_GRUPO` de
    grupos sanos de forma prematura e injusta. **Límite conocido, no
    resuelto del todo**: un grupo saludable que comparte pool con uno
    genuinamente fatal puede, en el peor caso (crashes que se solapan dos
    veces seguidas antes de que ese grupo sano termine), terminar cargado
    por una muerte ajena de todos modos -- es una consecuencia estructural
    de que `ProcessPoolExecutor` rompe el pool ENTERO ante un solo hijo
    muerto, no algo que este despachador pueda evitar del todo sin
    abandonar `ProcessPoolExecutor` (la decisión ya tomada por el proposal).
    En producción, donde los OOM-kill son eventos raros y no simultáneos,
    este caso extremo es infrecuente; en el peor caso, ese grupo termina en
    cuarentena (no pierde el documento, no tumba la corrida) y un reproceso
    manual posterior lo resuelve -- el mismo tratamiento que cualquier otro
    `ERROR_TRANSITORIO_AGOTADO`.

    **Tope de reintentos (`MAX_REINTENTOS_POR_GRUPO`)**: si un grupo agota
    sus reintentos (p. ej. su contenido dispara la muerte del proceso de
    forma determinística, no un OOM transitorio), se da por perdido: se
    registra en `cuarentena` un `ErrorDocumento` por cada referencia del
    grupo (`_dar_por_perdido`/`_error_grupo_perdido`) y la corrida SIGUE con los demás
    grupos -- nunca propaga la excepción hacia arriba. Registrar en
    `cuarentena` (no solo devolver un resultado en memoria) es necesario
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
    ).ejecutar()
