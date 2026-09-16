"""Lanzador de corridas: único punto donde nace una corrida. Crea la fila `corrida`,
inventaría vía `FuenteLocal` + `RepositorioCorridas.registrar_documentos`, y devuelve
`corrida_id` junto con las referencias listas para `tareas.procesar_grupo`.
`INVENTARIANDO -> PROCESANDO` NO la hace `lanzar()`: inventariar y procesar son cosas
distintas -- esa transición vive en `marcar_procesando`, llamada por quien realmente
va a procesar. Ningún cierre terminal se persiste acá: el panel deriva la marcha de
la evidencia, no del estado."""

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
    """Salvaguarda estructural: un generador agotado no avisa, así que iterar esta
    instancia una segunda vez explota con `RuntimeError` en vez de devolver una
    secuencia vacía silenciosa. No resuelve el caso de que el consumidor guarde el
    generador real de la primera `iter()` y lo reitere por su cuenta."""

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
    """Ya hay otra corrida activa -- gate a nivel de BASE, no un lock en memoria de un
    solo proceso: la base decide atómicamente sin importar qué proceso llame `lanzar()`."""

    def __init__(self, id_corrida_activa: str | None) -> None:
        self.id_corrida_activa = id_corrida_activa
        detalle = f" ({id_corrida_activa})" if id_corrida_activa else ""
        super().__init__(f"ya hay una corrida activa{detalle} -- esperá a que termine antes de lanzar otra")


class CorridaNoEncontradaError(LookupError):
    """`id_corrida` no existe. La ruta la traduce a `404`: responder con ceros sería
    indistinguible de "existe pero no tiene nada para reintentar"."""

    def __init__(self, id_corrida: str) -> None:
        self.id_corrida = id_corrida
        super().__init__(f"no existe una corrida con id {id_corrida}")


@dataclass(frozen=True)
class CuarentenaDeCorrida:
    """Estampa la corrida en cada error antes de delegar en el sumidero real. Decora
    en vez de meterle estado de corrida a `FuenteLocal` (larga vida, construida una
    sola vez por worker)."""

    interna: SumideroCuarentena
    corrida_id: str

    def registrar(self, error: ErrorDocumento) -> None:
        self.interna.registrar(replace(error, corrida_id=self.corrida_id))


@dataclass(frozen=True)
class ResultadoLanzamiento:
    """Lo mínimo que necesita el despachador para encolar los grupos. `referencias`
    es un ITERADOR de GRUPOS de un solo uso, no una tupla materializada: iterarlo dos
    veces o `list(...)` pierde exactamente la propiedad que lo motiva -- retener la
    partición completa en memoria antes de despachar el primer grupo. Ver
    `LanzadorCorrida._inventariar_y_generar_referencias`."""

    corrida_id: str
    referencias: Iterator[tuple[dict[str, str], ...]]


@dataclass(frozen=True)
class LanzadorCorrida:
    """Crea la corrida y la inventaría por el puerto de ingesta. `repositorio.crear_corrida`
    se llama ANTES de inventariar (FK). `lanzar` es la única escritora de la transición
    `INVENTARIANDO`: un conflicto de versión acá es corrupción real, se propaga el error.
    No avanza a `PROCESANDO` -- ver `marcar_procesando`."""

    repositorio: RepositorioCorridas
    cuarentena: SumideroCuarentena
    tope_bytes: int | None = None
    tamano_lote_inventario: int = 1000

    def lanzar(self, ruta: Path) -> ResultadoLanzamiento:
        """Crea la corrida -- o falla con `CorridaEnCursoError` si la base rechaza una
        segunda corrida activa (`ux_corrida_una_activa`). La única protección real
        contra dos corridas simultáneas la impone la base acá, sin importar qué
        proceso la lanzó."""
        corrida_id = str(uuid4())
        corrida = Corrida.crear(corrida_id, ruta_autorizada=str(ruta))
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
        """Genera las referencias grupo a grupo -- no materializa la partición completa
        antes de despachar la primera. El registro en `documento_corrida` se
        buffer-iza hasta `tamano_lote_inventario`, no hasta el final de la corrida.
        Costo aceptado: si el proceso muere a mitad de camino, algunos documentos ya
        escritos en `estudio`/`cuarentena` pueden faltar en `documento_corrida` -- no
        se pierde ningún documento clínico, sólo trazabilidad administrativa."""
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
        """Avanza `corrida_id` a `PROCESANDO` y persiste -- o falla ruidoso. Separado
        de `lanzar()`: el que sólo inventaría no puede afirmar que está procesando.
        Lee la corrida desde el repositorio, no en memoria: el llamador puede ser un
        proceso distinto del que la creó."""
        self._transicionar(corrida_id, EstadoCorrida.PROCESANDO)

    def marcar_finalizada(self, corrida_id: str, *, hubo_cuarentena: bool) -> None:
        """Avanza `corrida_id` a un estado TERMINAL y persiste -- o falla ruidoso.
        Simétrico de `marcar_procesando`: cierra también el gate de "una corrida a la
        vez" para la siguiente. `hubo_cuarentena` viaja del llamador en vez de
        volver a consultar el embudo (lectura agregada más cara)."""
        destino = EstadoCorrida.COMPLETADA_CON_CUARENTENA if hubo_cuarentena else EstadoCorrida.COMPLETADA
        self._transicionar(corrida_id, destino)

    def marcar_fallida(self, corrida_id: str) -> None:
        """Cierra `corrida_id` como `FALLIDA` -- backstop ante una excepción inesperada
        que rompe el hilo de despacho entero, distinta de una cuarentena por documento."""
        self._transicionar(corrida_id, EstadoCorrida.FALLIDA)

    def _transicionar(self, corrida_id: str, destino: EstadoCorrida) -> None:
        """Lee `corrida_id`, avanza a `destino` y persiste -- o falla ruidoso si la
        corrida no existe. Idempotente si `corrida_id` ya está en `destino`: sin este
        no-op, una segunda transición síncrona explotaría contra `_TRANSICIONES_CORRIDA`."""
        corrida = self.repositorio.obtener_corrida(corrida_id)
        if corrida is None:
            raise ValueError(f"no existe una corrida con id {corrida_id}")
        if corrida.estado is destino:
            return
        self._avanzar_y_persistir(corrida, destino)

    def _avanzar_y_persistir(self, corrida: Corrida, destino: EstadoCorrida) -> None:
        """Avanza `corrida` en memoria y persiste, o falla ruidoso. Si el `RuntimeError`
        se dispara, hoy sólo puede ser por corrupción externa a la fila (no hay dos
        llamadores compitiendo en operación normal). Recuperación manual: corregir
        estado/version contra la versión real; nunca reintentar la operación."""
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


# Generoso a propósito: documento_corrida no tiene columna de tiempo, así que una
# corrida sólo inventariando no deja evidencia más allá de su última transición.
# Conservador en la dirección segura: preferir no recuperar antes que pisar trabajo real.
MARGEN_INACTIVIDAD_DEFAULT = timedelta(minutes=15)


def recuperar_corridas_abandonadas(
    repositorio: RepositorioCorridas,
    *,
    margen_inactividad: timedelta = MARGEN_INACTIVIDAD_DEFAULT,
    ahora: datetime | None = None,
) -> list[str]:
    """Cierra como `FALLIDA` toda corrida no terminal SIN evidencia reciente de
    trabajo, al arrancar el servidor. NO asume "servidor de un solo proceso ⇒ toda
    corrida no terminal está abandonada" (falso: otro proceso puede seguir escribiendo
    contra la misma base sin marcar el cierre). `RepositorioCorridas.ultima_actividad`
    da la evidencia real -- el máximo entre la última transición administrativa y el
    `estudio`/`cuarentena` más reciente, sin importar qué proceso lo escribió. Asume un
    único proceso SERVIDOR (sin réplicas del panel). Devuelve los `id_corrida`
    recuperados para que el llamador los loguee."""
    momento = ahora if ahora is not None else datetime.now(timezone.utc)
    # SQLite (tests) devuelve datetime NAIVE incluso con timezone=True; Postgres no.
    # Normalizar a naive-UTC evita TypeError al comparar, sin depender del motor.
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
