"""Lanzador de corridas: único punto donde nace una corrida (design.md, "Recorrido").

Arranque, una sola vez, fuera del camino caliente: crea la fila `corrida`,
inventaría vía `FuenteLocal` + `RepositorioCorridas.registrar_documentos`, y
devuelve `corrida_id` junto con las referencias listas para
`trabajadores.tareas.procesar_grupo` (misma forma exacta que exige su
centinela de claves: `{id_documento, uri, sha256}`).

Este módulo no importa `pipeline`: sigue la misma regla que `ingesta/fuente.py`
(`SumideroCuarentena` propio, satisfecho por tipado estructural).

Las transiciones `CREADA -> INVENTARIANDO -> PROCESANDO` SÍ se persisten
(hallazgo post-Fase 9, `panel-de-operacion`): `Corrida.avanzar_a` las valida
en memoria, pero sin escribirlas de vuelta con
`RepositorioCorridas.actualizar_corrida` la fila de `corrida` queda en
`creada` para siempre y el campo `estado` del JSON del embudo
(`ServicioCorridasReal`) miente durante toda la corrida. No se persiste
ningún cierre en estados terminales -- eso sigue fuera de alcance
(design.md, "Fuera de alcance"): el panel deriva la marcha de la evidencia,
no del estado (Decisión 8); esto es sólo trazabilidad administrativa de las
tres transiciones que sí ocurren de verdad.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.errores import ErrorDocumento
from anonimizacion.dominio.estados_corrida import EstadoCorrida

from .fuente import FuenteLocal, SumideroCuarentena
from .repositorio_corridas import RepositorioCorridas


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
    """Lo mínimo que necesita el despachador para encolar el grupo."""

    corrida_id: str
    referencias: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class LanzadorCorrida:
    """Crea la corrida, inventaría por el puerto de ingesta y avanza el estado.

    `repositorio.crear_corrida` se llama ANTES de inventariar: `documento_corrida.corrida_id`
    es FK contra `corrida.id_corrida` (sin FK no hay dónde insertar el
    inventario). Las transiciones `INVENTARIANDO`/`PROCESANDO` se validan en
    el objeto `Corrida` en memoria y se persisten con
    `RepositorioCorridas.actualizar_corrida` inmediatamente después de cada
    una -- mismo bloqueo optimista que ya usa `actualizar_documento`. `lanzar`
    es la única escritora de esta corrida en todo su recorrido (nadie más
    llama `avanzar_a` sobre ella), así que un conflicto de versión acá sería
    una corrupción real, no una carrera esperable: se deja propagar el
    `RuntimeError` en vez de tragarlo.
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
        artefactos = list(fuente.listar())

        documentos = [
            DocumentoCorrida.inventariado(
                corrida_id=corrida_id,
                huella_contenido=artefacto.sha256,
                ruta_autorizada=artefacto.uri,
            )
            for artefacto in artefactos
        ]
        self.repositorio.registrar_documentos(documentos, tamano_lote=self.tamano_lote_inventario)

        self._avanzar_y_persistir(corrida, EstadoCorrida.PROCESANDO)

        referencias = tuple(
            {"id_documento": artefacto.sha256, "uri": artefacto.uri, "sha256": artefacto.sha256}
            for artefacto in artefactos
        )
        return ResultadoLanzamiento(corrida_id=corrida_id, referencias=referencias)

    def _avanzar_y_persistir(self, corrida: Corrida, destino: EstadoCorrida) -> None:
        """Avanza `corrida` en memoria y persiste, o falla ruidoso.

        Nota operativa (revisión fresca, panel-de-operacion): si este
        `RuntimeError` se dispara en la SEGUNDA llamada (la transición a
        `PROCESANDO`), el inventario ya se escribió y comiteó por completo
        (`registrar_documentos` corrió antes, y es lo único que se ejecuta
        entre las dos llamadas) -- sólo la fila de `corrida` quedó sin
        avanzar, trabada en `inventariando`. Hoy esto sólo puede pasar por
        corrupción externa a la fila de `corrida` (un `UPDATE` manual, una
        migración que le tocó la columna `version`): cada `lanzar()` genera
        su propio `corrida_id` con `uuid4()`, así que no hay dos llamadores
        compitiendo por la misma fila -- no hay carrera real que lo dispare
        en operación normal.

        Si aparece de todos modos: NO hay una segunda corrida a la que
        migrar el inventario ya escrito (`documento_corrida` está atado a
        este `corrida_id` por FK) y NO hay un método para forzar el avance
        de `corrida.estado` sin pasar por `Corrida.avanzar_a` (a propósito:
        saltarse esa validación es la misma clase de puerta trasera que este
        cambio evita en otros lados). La recuperación manual correcta es leer
        `corrida.version` real desde la base, confirmar que el inventario
        de `documento_corrida` para este `corrida_id` está completo, y
        corregir `corrida.estado`/`version` a mano contra esa versión real
        -- no reintentar `lanzar()`, que generaría un `corrida_id` nuevo y
        un inventario duplicado del mismo directorio. No hay automatismo
        para este caso: es deliberado, para no enmascarar la corrupción que
        lo causó.
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
