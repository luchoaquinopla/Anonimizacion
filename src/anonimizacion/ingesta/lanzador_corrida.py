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
from pathlib import Path
from uuid import uuid4

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
        corrida_id = str(uuid4())
        corrida = Corrida.crear(corrida_id)
        self.repositorio.crear_corrida(corrida)
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
        corrida = self.repositorio.obtener_corrida(corrida_id)
        if corrida is None:
            raise ValueError(f"no existe una corrida con id {corrida_id}")
        self._avanzar_y_persistir(corrida, EstadoCorrida.PROCESANDO)

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
