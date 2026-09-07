"""Lanzador de corridas: único punto donde nace una corrida (design.md, "Recorrido").

Arranque, una sola vez, fuera del camino caliente: crea la fila `corrida`,
inventaría vía `FuenteLocal` + `RepositorioCorridas.registrar_documentos`, y
devuelve `corrida_id` junto con las referencias listas para
`trabajadores.tareas.procesar_grupo` (misma forma exacta que exige su
centinela de claves: `{id_documento, uri, sha256}`).

Este módulo no importa `pipeline`: sigue la misma regla que `ingesta/fuente.py`
(`SumideroCuarentena` propio, satisfecho por tipado estructural).

La transición `CREADA -> INVENTARIANDO` SÍ se persiste (hallazgo post-Fase 9,
`panel-de-operacion`): `Corrida.avanzar_a` la valida en memoria, pero sin
escribirla de vuelta con `RepositorioCorridas.actualizar_corrida` la fila de
`corrida` queda en `creada` para siempre y el campo `estado` del JSON del
embudo (`ServicioCorridasReal`) miente durante toda la corrida.

`INVENTARIANDO -> PROCESANDO` NO la hace `lanzar()` (cierre de silencio de
auditoría, `fix/silencios-de-ingesta-y-panel`): inventariar y procesar son
cosas distintas, y `lanzar()` sólo inventaría -- no encola ni ejecuta nada.
Antes avanzaba igual el estado hasta `PROCESANDO`, así que una corrida creada
vía `POST /corridas` quedaba diciendo "procesando" para siempre sin que nada
la procesara. Esa transición vive en `marcar_procesando`, que debe llamar
quien realmente vaya a procesar el inventario (hoy `scripts/procesar_carpeta.py`,
el único llamador de `trabajadores.tareas.procesar_grupo` en todo el
repositorio; a futuro, el despachador real) -- quien avanza el estado tiene
que ser quien hace el trabajo.

No se persiste ningún cierre en estados terminales -- eso sigue fuera de
alcance (design.md, "Fuera de alcance"): el panel deriva la marcha de la
evidencia, no del estado (Decisión 8); esto es sólo trazabilidad
administrativa de las transiciones que sí ocurren de verdad.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.errores import ErrorDocumento
from anonimizacion.dominio.estados_corrida import EstadoCorrida

from .fuente import FuenteLocal, SumideroCuarentena
from .repositorio_corridas import RepositorioCorridas


class _IteradorDeUnSoloUso:
    """Salvaguarda estructural (revisión adversarial, MEDIO): el docstring de
    `ResultadoLanzamiento.referencias` ya advertía que es de un solo uso, pero
    nada impedía que un consumidor futuro lo iterara dos veces y perdiera
    todos los grupos en silencio la segunda vez (un generador agotado
    simplemente no produce nada más, sin avisar). Esto lo convierte en un
    fallo ruidoso: la SEGUNDA vez que algo pide un iterador sobre esta
    instancia -- via `iter(...)` o `next(...)` directo -- explota con
    `RuntimeError` en vez de devolver una secuencia vacía silenciosa.

    Deliberadamente NO resuelve el caso de que un consumidor guarde el
    resultado de la PRIMERA `iter()` (el generador real, ya desenvuelto) y lo
    reitere por su cuenta -- eso excede lo que una envoltura puede prevenir
    sin materializar la secuencia, que es justo lo que este cambio evita. Es
    una defensa barata contra el error más común (llamar `list(...)` o iterar
    dos veces sobre el objeto que devolvió `lanzar()`), no una garantía total.
    """

    def __init__(self, generador: Iterator[tuple[dict[str, str], ...]]) -> None:
        self._generador = generador
        self._entregado = False

    def _marcar_entregado_o_fallar(self) -> Iterator[tuple[dict[str, str], ...]]:
        if self._entregado:
            raise RuntimeError(
                "ResultadoLanzamiento.referencias ya fue consumido -- es un iterador de "
                "un solo uso (ver su docstring). Iterarlo una segunda vez perdería todos "
                "los grupos en silencio (un generador agotado no produce nada más sin "
                "avisar); se prefiere fallar ruidoso. Si necesitás la cuenta total, "
                "contá mientras iterás la única vez que lo consumís."
            )
        self._entregado = True
        return self._generador

    def __iter__(self) -> Iterator[tuple[dict[str, str], ...]]:
        return self._marcar_entregado_o_fallar()

    def __next__(self) -> tuple[dict[str, str], ...]:
        return next(self._marcar_entregado_o_fallar())


class CorridaEnCursoError(RuntimeError):
    """Ya hay otra corrida activa -- gate a nivel de BASE (revisión
    adversarial ronda 3, hallazgo 4, feature `despachador-desde-el-panel`).

    Movida acá desde `web/servicio_corridas.py` (donde vivía como chequeo de
    sólo un `threading.Lock` de UN proceso): confirmado que
    `scripts/procesar_carpeta.py` NO llama `listar_corridas_no_terminales`
    en ningún punto -- no tiene gate propio. Un lock en memoria del panel
    jamás podría proteger contra ese script (otro proceso) lanzando una
    corrida real mientras el panel ya procesa una -- las dos convivirían sin
    que nada las detecte hasta agotar la memoria (~875 MB × `procesos` cada
    una).

    `LanzadorCorrida.lanzar()` es el único punto donde nace una corrida
    (design.md, "Recorrido") -- así que es el lugar correcto para traducir
    el rechazo de `ux_corrida_una_activa` (`modelos_orm.py`, índice único
    parcial: `WHERE activa`, `activa` mantenida por `RepositorioCorridas` en
    cada escritura de `corrida.estado`) en un error de dominio legible. La
    base decide atómicamente, sin importar qué proceso llame `lanzar()` ni
    en qué orden -- no un lock en memoria de un solo proceso.
    """

    def __init__(self, id_corrida_activa: str | None) -> None:
        self.id_corrida_activa = id_corrida_activa
        detalle = f" ({id_corrida_activa})" if id_corrida_activa else ""
        super().__init__(f"ya hay una corrida activa{detalle} -- esperá a que termine antes de lanzar otra")


@dataclass(frozen=True)
class CuarentenaDeCorrida:
    """Estampa la corrida en cada error antes de delegar en el sumidero real.

    Existe porque la ingesta aparta artefactos que nunca llegan al ejecutor
    (`FuenteLocal._apartar_por_sobretamano` corre ANTES de calcular el sha256,
    así que ese artefacto no puede inventariarse ni pasar por `_a_fallo`, el
    único otro punto donde el `corrida_id` está en mano). Decorar el sumidero
    en vez de meterle estado de corrida a `FuenteLocal` -- que es un
    dataclass frozen construido una sola vez por worker -- evita acoplar una
    entidad de una sola vez (una corrida) a un objeto de larga vida.
    """

    interna: SumideroCuarentena
    corrida_id: str

    def registrar(self, error: ErrorDocumento) -> None:
        self.interna.registrar(replace(error, corrida_id=self.corrida_id))


@dataclass(frozen=True)
class ResultadoLanzamiento:
    """Lo mínimo que necesita el despachador para encolar los grupos.

    `referencias` es un ITERADOR de GRUPOS -- no una tupla plana, y desde la
    revisión adversarial que encontró el hallazgo crítico 2, tampoco una
    tupla de grupos ya materializada. Cada grupo es a su vez una tupla de
    referencias `{id_documento, uri, sha256}`, en la forma exacta que exige
    `trabajadores.tareas.procesar_grupo`. Antes de este cambio la carpeta
    entera viajaba como un solo lote (`tareas.py` documentaba "un paciente,
    un episodio" de forma aspiracional, sin que ningún código lo garantizara
    -- `procesar_lote` terminaba acumulando en RAM los resueltos de la
    corrida completa). Ver `ingesta/fuente.py::FuenteLocal.listar_grupos`
    para el criterio de agrupamiento real.

    **Consumo de UN SOLO USO**: `referencias` es un generador, no una
    colección. `list(resultado.referencias)` o iterarlo dos veces pierde
    exactamente la propiedad que lo motiva -- si necesitás la cuenta total,
    contá mientras iterás una única vez, no materialices para despues medir.
    `LanzadorCorrida.lanzar()` hacía `list(fuente.listar_grupos())` ANTES de
    construir esta tupla (revisión adversarial, hallazgo crítico 2): eso
    retenía la partición completa en memoria antes de despachar el primer
    grupo, mudando a este punto el mismo problema de RAM que motiva
    `listar_grupos()`. Ver `LanzadorCorrida._inventariar_y_generar_referencias`
    para cómo se resolvió."""

    corrida_id: str
    referencias: Iterator[tuple[dict[str, str], ...]]


@dataclass(frozen=True)
class LanzadorCorrida:
    """Crea la corrida y la inventaría por el puerto de ingesta.

    `repositorio.crear_corrida` se llama ANTES de inventariar: `documento_corrida.corrida_id`
    es FK contra `corrida.id_corrida` (sin FK no hay dónde insertar el
    inventario). La transición `INVENTARIANDO` se valida en el objeto
    `Corrida` en memoria y se persiste con `RepositorioCorridas.actualizar_corrida`
    inmediatamente después -- mismo bloqueo optimista que ya usa
    `actualizar_documento`. `lanzar` es la única escritora de esta transición
    en todo el recorrido de la corrida (nadie más llama `avanzar_a` con
    `INVENTARIANDO` sobre ella), así que un conflicto de versión acá sería una
    corrupción real, no una carrera esperable: se deja propagar el
    `RuntimeError` en vez de tragarlo.

    `lanzar` NO avanza a `PROCESANDO`: inventariar y procesar son cosas
    distintas, y `lanzar` sólo inventaría -- no encola ni ejecuta nada. Quien
    avanza el estado tiene que ser quien hace el trabajo; ver `marcar_procesando`.
    """

    repositorio: RepositorioCorridas
    cuarentena: SumideroCuarentena
    tope_bytes: int | None = None
    tamano_lote_inventario: int = 1000

    def lanzar(self, ruta: Path) -> ResultadoLanzamiento:
        """Crea la corrida -- o falla con `CorridaEnCursoError` si la base
        rechaza una segunda corrida activa (`ux_corrida_una_activa`, revisión
        adversarial ronda 3, hallazgo 4). Este `try` es lo único que hace que
        el gate de "una corrida a la vez" alcance a `scripts/procesar_carpeta.py`:
        ese script no tiene ningún chequeo propio, así que la única
        protección real que le llega es la que la BASE le impone acá mismo,
        sin importar qué otro proceso (p. ej. el panel) haya lanzado la
        corrida que sigue activa.
        """
        corrida_id = str(uuid4())
        corrida = Corrida.crear(corrida_id)
        try:
            self.repositorio.crear_corrida(corrida)
        except IntegrityError as error:
            activas = self.repositorio.listar_corridas_no_terminales()
            id_activa = activas[0].id_corrida if activas else None
            raise CorridaEnCursoError(id_activa) from error
        self._avanzar_y_persistir(corrida, EstadoCorrida.INVENTARIANDO)

        sumidero = CuarentenaDeCorrida(interna=self.cuarentena, corrida_id=corrida_id)
        fuente = FuenteLocal(
            raices=(ruta,),
            directorio=ruta,
            cuarentena=sumidero,
            **({"tope_bytes": self.tope_bytes} if self.tope_bytes is not None else {}),
        )
        referencias = _IteradorDeUnSoloUso(self._inventariar_y_generar_referencias(fuente, corrida_id))
        return ResultadoLanzamiento(corrida_id=corrida_id, referencias=referencias)

    def _inventariar_y_generar_referencias(
        self, fuente: FuenteLocal, corrida_id: str
    ) -> Iterator[tuple[dict[str, str], ...]]:
        """Genera las referencias GRUPO A GRUPO -- no materializa la partición
        completa antes de despachar la primera (revisión adversarial,
        hallazgo crítico 2: la versión anterior hacía
        `grupos = list(fuente.listar_grupos())`, retenía TODA la partición en
        memoria antes de que el llamador pudiera empezar a procesar el primer
        grupo, mudando a este punto exacto el mismo problema de RAM que este
        cambio existe para resolver).

        El registro en `documento_corrida` (`RepositorioCorridas.registrar_documentos`)
        se buffer-iza hasta `tamano_lote_inventario` documentos, no hasta el
        final de la corrida entera: memoria acotada a un múltiplo chico y
        constante de ese tamaño (el mismo tamaño de lote que ya usaba el
        registro flat), nunca al tamaño del corpus. `entraron` (consumido por
        el embudo vía `RepositorioCorridas`) sigue naciendo acá, en un solo
        proceso -- lo único que cambia es CUÁNDO se persiste cada tramo del
        inventario, no CUÁNTOS documentos entran en total.

        Costo aceptado y explícito: antes, si `registrar_documentos` fallaba,
        `lanzar()` completo fallaba ANTES de que el llamador pudiera despachar
        ningún grupo (todo o nada). Ahora un grupo puede despacharse y
        procesarse antes de que su propia fila `documento_corrida` esté
        commiteada (se persiste cuando el buffer llega al tope, o al agotar
        el generador). Si el proceso muere a mitad de una corrida, algunos
        documentos ya escritos en `estudio`/`cuarentena` (con `corrida_id`
        propio) pueden faltar en `documento_corrida` -- no se pierde ningún
        documento clínico, sólo un renglón de trazabilidad administrativa
        (la misma tabla que este módulo ya declara "trazabilidad
        administrativa de las transiciones que sí ocurren de verdad", no la
        autoridad de qué se publicó).
        """
        buffer: list[DocumentoCorrida] = []
        for grupo in fuente.listar_grupos():
            for artefacto in grupo:
                buffer.append(
                    DocumentoCorrida.inventariado(
                        corrida_id=corrida_id,
                        huella_contenido=artefacto.sha256,
                        ruta_autorizada=artefacto.uri,
                    )
                )
            if len(buffer) >= self.tamano_lote_inventario:
                self.repositorio.registrar_documentos(buffer, tamano_lote=self.tamano_lote_inventario)
                buffer = []
            yield tuple(
                {"id_documento": artefacto.sha256, "uri": artefacto.uri, "sha256": artefacto.sha256}
                for artefacto in grupo
            )
        if buffer:
            self.repositorio.registrar_documentos(buffer, tamano_lote=self.tamano_lote_inventario)

    def marcar_procesando(self, corrida_id: str) -> None:
        """Avanza `corrida_id` a `PROCESANDO` y persiste -- o falla ruidoso.

        Separado de `lanzar()` (cierre de silencio de auditoría,
        `fix/silencios-de-ingesta-y-panel`): inventariar y procesar son cosas
        distintas, y el que sólo inventaría no puede afirmar que está
        procesando. Debe llamarlo quien REALMENTE va a procesar el inventario,
        inmediatamente antes de encolar/ejecutar -- hoy
        `scripts/procesar_carpeta.py` (el único llamador de
        `trabajadores.tareas.procesar_grupo` en todo el repositorio), a futuro
        el despachador real que la reemplace.

        Lee la corrida desde el repositorio (no la recibe en memoria): a
        diferencia de `lanzar()`, el llamador de este método puede ser un
        proceso distinto del que la creó (p. ej. un worker que retoma
        `corrida_id` desde una cola), así que no puede asumir que tiene el
        objeto `Corrida` a mano.
        """
        self._transicionar(corrida_id, EstadoCorrida.PROCESANDO)

    def marcar_finalizada(self, corrida_id: str, *, hubo_cuarentena: bool) -> None:
        """Avanza `corrida_id` a un estado TERMINAL y persiste -- o falla ruidoso.

        Simétrico de `marcar_procesando` en el otro extremo (feature
        `despachador-desde-el-panel`): quien REALMENTE terminó de despachar
        el inventario tiene que ser quien cierra la corrida -- hoy
        `ServicioCorridasReal`, el despachador desde el panel. Sin esto, una
        corrida procesada de punta a punta queda diciendo `procesando` para
        siempre: la misma clase de mentira que `marcar_procesando` cerró en
        la punta de arranque, ahora en la punta de cierre. Cerrarla también
        es lo que libera el gate de "una corrida a la vez"
        (`RepositorioCorridas.listar_corridas_no_terminales`) para la
        siguiente corrida.

        `PROCESANDO -> {COMPLETADA, COMPLETADA_CON_CUARENTENA}` DIRECTA, sin
        pasar por `RECONCILIANDO`/`PUBLICANDO` (ver el comentario junto a
        `_TRANSICIONES_CORRIDA` en `dominio/corridas.py`): en esta
        arquitectura, `procesar_grupo` ya reconcilia y publica cada grupo de
        punta a punta en una sola llamada síncrona -- no hay una fase
        administrativa separada que atravesar.

        `hubo_cuarentena`: quien despachó ya sabe, al terminar
        `despachar_en_paralelo`, si algún documento terminó en cuarentena --
        se lo pasa acá en vez de que este método vuelva a consultar el
        embudo, que es una lectura agregada más cara y ya resuelta por el
        llamador.

        Lee la corrida desde el repositorio, igual que `marcar_procesando`:
        el llamador puede ser un hilo/proceso distinto del que la creó.
        """
        destino = EstadoCorrida.COMPLETADA_CON_CUARENTENA if hubo_cuarentena else EstadoCorrida.COMPLETADA
        self._transicionar(corrida_id, destino)

    def marcar_fallida(self, corrida_id: str) -> None:
        """Cierra `corrida_id` como `FALLIDA` -- backstop del despachador
        (feature `despachador-desde-el-panel`) ante una excepción INESPERADA
        que rompe el hilo de despacho entero, distinta de una cuarentena por
        documento (`despachar_en_paralelo` nunca propaga esas: quedan
        registradas en `cuarentena` y la corrida sigue). Sin esto, una
        corrida cuyo despacho crasheó por una razón no contemplada (un `pool`
        que no pudo crearse, un `ValueError` de validación, etc.) quedaría
        `procesando` para siempre -- la misma mentira que este cambio existe
        para cerrar, en su forma más inesperada.
        """
        self._transicionar(corrida_id, EstadoCorrida.FALLIDA)

    def _transicionar(self, corrida_id: str, destino: EstadoCorrida) -> None:
        """Lee `corrida_id`, avanza a `destino` y persiste -- o falla ruidoso
        si la corrida no existe. Compartido por `marcar_procesando`,
        `marcar_finalizada` y `marcar_fallida`: los tres leen la corrida
        desde el repositorio (nunca en memoria, a diferencia de `lanzar()`)
        porque su llamador puede ser un hilo/proceso distinto del que la
        creó."""
        corrida = self.repositorio.obtener_corrida(corrida_id)
        if corrida is None:
            raise ValueError(f"no existe una corrida con id {corrida_id}")
        self._avanzar_y_persistir(corrida, destino)

    def _avanzar_y_persistir(self, corrida: Corrida, destino: EstadoCorrida) -> None:
        """Avanza `corrida` en memoria y persiste, o falla ruidoso.

        Nota operativa (revisión fresca, panel-de-operacion): si este
        `RuntimeError` se dispara, la fila de `corrida` quedó sin avanzar a
        `destino`, trabada en el estado anterior. Hoy esto sólo puede pasar
        por corrupción externa a la fila de `corrida` (un `UPDATE` manual, una
        migración que le tocó la columna `version`): cada `lanzar()` genera
        su propio `corrida_id` con `uuid4()`, y `marcar_procesando()` lee la
        versión real justo antes de avanzar, así que no hay dos llamadores
        compitiendo por la misma fila en operación normal.

        Si aparece de todos modos: NO hay un método para forzar el avance de
        `corrida.estado` sin pasar por `Corrida.avanzar_a` (a propósito:
        saltarse esa validación es la misma clase de puerta trasera que este
        cambio evita en otros lados). La recuperación manual correcta es leer
        `corrida.version` real desde la base y corregir `corrida.estado`/`version`
        a mano contra esa versión real -- no reintentar la operación que
        falló, que podría duplicar trabajo según el llamador. No hay
        automatismo para este caso: es deliberado, para no enmascarar la
        corrupción que lo causó.
        """
        version_antes = corrida.version
        corrida.avanzar_a(destino)
        if not self.repositorio.actualizar_corrida(corrida, version_esperada=version_antes):
            raise RuntimeError(
                f"actualizar_corrida rechazo la transicion a {destino.value} para "
                f"{corrida.id_corrida}: la version persistida ya no era {version_antes}. "
                "lanzar() es la unica escritora de esta corrida -- esto es una corrupcion "
                "real, no una carrera esperable. Ver el docstring de _avanzar_y_persistir "
                "para la recuperacion manual."
            )


# Margen de inactividad por defecto para `recuperar_corridas_abandonadas`
# (revisión adversarial crítico 1): tiene que ser generoso porque
# `documento_corrida` (el inventario) no tiene columna de tiempo -- una
# corrida que tarda mucho SÓLO inventariando (antes del primer `estudio`/
# `cuarentena`) no deja evidencia nueva más allá de su última transición
# administrativa. 15 minutos es más que el tiempo típico de un grupo
# (segundos a bajas decenas de segundos, ver `despacho_paralelo.py`) y dista
# mucho de las horas que dura una corrida real -- conservador en la
# dirección segura: preferir NO recuperar una corrida dudosa antes que
# pisar trabajo real de otro proceso.
MARGEN_INACTIVIDAD_DEFAULT = timedelta(minutes=15)


def recuperar_corridas_abandonadas(
    repositorio: RepositorioCorridas,
    *,
    margen_inactividad: timedelta = MARGEN_INACTIVIDAD_DEFAULT,
    ahora: datetime | None = None,
) -> list[str]:
    """Cierra como `FALLIDA` toda corrida no terminal SIN evidencia reciente
    de trabajo, al arrancar el servidor (feature `despachador-desde-el-panel`,
    decisión "qué pasa si el servidor se cae con una corrida en curso").

    Llamador de producción: `scripts/servir_panel.py::construir_aplicacion`,
    UNA vez, antes de empezar a servir peticiones.

    CORRECCIÓN (revisión adversarial crítico 1): la versión anterior asumía
    "servidor de un solo proceso ⇒ toda corrida no terminal está abandonada".
    Es falso -- reproducido contra Postgres real. `scripts/procesar_carpeta.py`
    usa el MISMO `LanzadorCorrida` contra la MISMA base por defecto, en OTRO
    proceso, y NUNCA llama `marcar_finalizada`/`marcar_fallida`: dejar una
    corrida en `PROCESANDO` mientras sigue escribiendo `estudio`/`cuarentena`
    es su comportamiento NORMAL, no un bug. Si el panel arranca mientras ese
    script sigue corriendo, la versión anterior la marcaba `FALLIDA` a mitad
    de la escritura -- la inversión exacta del defecto que cerró el PR #33
    (antes "procesando" sin que nada procese; con ese bug, "fallida" mientras
    algo sí procesa). Y en cadena: como `FALLIDA` es terminal,
    `listar_corridas_no_terminales` dejaba de verla, reabriendo el gate de
    "una corrida a la vez" para una segunda corrida que duplicaría el
    presupuesto de memoria de la que seguía viva.

    La corrección: un proceso no puede decidir que el trabajo de OTRO está
    muerto sin evidencia. `RepositorioCorridas.ultima_actividad` da esa
    evidencia -- el máximo entre la última transición administrativa de
    `corrida` y el `estudio`/`cuarentena` más reciente escrito bajo su
    `corrida_id`, sin importar qué proceso lo escribió. Sólo se recupera una
    corrida no terminal si esa evidencia es más vieja que `margen_inactividad`
    (o no existe ninguna). Esto SIGUE distinguiendo "abandonada" de "viva en
    otro proceso" sin necesitar saber NADA sobre quién es ese otro proceso --
    ni su PID, ni un latido dedicado, ni una marca de pertenencia: la
    evidencia es el mismo dato que el panel ya usa para todo lo demás
    (Decisión 8, "el panel deriva la marcha de la evidencia, no del estado").

    `ahora`/`margen_inactividad` inyectables (mismo patrón que `reloj` en
    `web/embudo_corrida.py::construir_embudo`): producción usa el default y
    el reloj real; los tests fijan ambos para no depender de dormir de verdad.

    `FALLIDA`, no un intento de reanudación: la reanudación por documento
    está fuera de alcance (`reintentar_corrida` sigue devolviendo 501, ver
    `web/rutas_corridas.py`) -- sin ella, no hay forma honesta de saber
    cuánto del inventario ya se procesó antes de la caída. Los documentos que
    sí llegaron a escribirse en `estudio`/`cuarentena` (Postgres, con su
    propio `corrida_id`) no se pierden ni se revierten: sólo el renglón
    administrativo de `corrida` queda `FALLIDA`, la misma distinción que ya
    hace `LanzadorCorrida._inventariar_y_generar_referencias` entre
    trazabilidad administrativa y datos clínicos reales.

    Asume un ÚNICO proceso SERVIDOR (sin réplicas ni balanceador delante del
    panel): con más de una instancia de PANEL corriendo a la vez, una corrida
    recién creada por la instancia A podría verse como "abandonada" desde el
    arranque de la instancia B si no llegó a dejar evidencia todavía. El
    diseño actual (`servir_panel.py`, sin autenticación, documentado para la
    intranet de un solo instituto) no contempla ese despliegue -- si aparece,
    este supuesto necesita revisarse primero. Este supuesto NO se extiende a
    "único proceso que escribe en la base": `scripts/procesar_carpeta.py` (u
    otro despachador futuro) puede seguir escribiendo en paralelo, y la
    evidencia real es justamente lo que lo protege.

    LIMITACIÓN CONOCIDA, ACEPTADA: una corrida genuinamente abandonada cuya
    ÚLTIMA evidencia cae DENTRO del margen no se recupera en esta pasada --
    queda para el próximo arranque del panel. Preferible al error opuesto
    (marcar `FALLIDA` algo que sigue vivo): ver el docstring de
    `ultima_actividad` para el caso sin cubrir (corrida que tarda mucho SÓLO
    inventariando).

    Devuelve los `id_corrida` recuperados, para que el llamador pueda
    loguearlos (visibilidad operativa: el médico que reinicia el panel
    después de una caída debe poder ver qué corrida se perdió).
    """
    momento = ahora if ahora is not None else datetime.now(timezone.utc)
    # `.replace(tzinfo=None)`: Postgres devuelve `datetime` con tz real, pero
    # SQLite (usado en tests) devuelve NAIVE incluso para columnas
    # `DateTime(timezone=True)` -- el driver no persiste el offset. Todo el
    # sistema ya asume UTC por convención (`_ahora_utc()`,
    # `modelos_orm.py`), así que normalizar a naive-UTC antes de comparar es
    # seguro y evita `TypeError: can't compare offset-naive and offset-aware
    # datetimes` sin depender de qué motor está detrás.
    umbral = (momento - margen_inactividad).replace(tzinfo=None)
    recuperados: list[str] = []
    for corrida in repositorio.listar_corridas_no_terminales():
        ultima = repositorio.ultima_actividad(corrida.id_corrida)
        if ultima is not None and ultima.replace(tzinfo=None) >= umbral:
            continue  # evidencia reciente: sigue viva en OTRO proceso, no se toca
        version_antes = corrida.version
        corrida.avanzar_a(EstadoCorrida.FALLIDA)
        if repositorio.actualizar_corrida(corrida, version_esperada=version_antes):
            recuperados.append(corrida.id_corrida)
    return recuperados
