"""Lanzador de corridas: único punto donde nace una corrida (design.md, "Recorrido").

Arranque, una sola vez, fuera del camino caliente: crea la fila `corrida`,
inventaría vía `FuenteLocal` + `RepositorioCorridas.registrar_documentos`, y
devuelve `corrida_id` junto con las referencias listas para
`trabajadores.tareas.procesar_grupo` (misma forma exacta que exige su
centinela de claves: `{id_documento, uri, sha256}`).

Este módulo no importa `pipeline`: sigue la misma regla que `ingesta/fuente.py`
(`SumideroCuarentena` propio, satisfecho por tipado estructural).
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
    el objeto `Corrida` en memoria (fallan ruidoso si el orden fuera
    inválido) pero no se vuelven a persistir: ningún consumidor de este
    tramo lee `corrida.estado` de vuelta, y agregar un método de
    actualización sin ese llamador sería la misma pieza huérfana que este
    cambio evita en otros lados.
    """

    repositorio: RepositorioCorridas
    cuarentena: SumideroCuarentena
    tope_bytes: int | None = None
    tamano_lote_inventario: int = 1000

    def lanzar(self, ruta: Path) -> ResultadoLanzamiento:
        corrida_id = str(uuid4())
        corrida = Corrida.crear(corrida_id)
        self.repositorio.crear_corrida(corrida)
        corrida.avanzar_a(EstadoCorrida.INVENTARIANDO)

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

        corrida.avanzar_a(EstadoCorrida.PROCESANDO)

        referencias = tuple(
            {"id_documento": artefacto.sha256, "uri": artefacto.uri, "sha256": artefacto.sha256}
            for artefacto in artefactos
        )
        return ResultadoLanzamiento(corrida_id=corrida_id, referencias=referencias)
