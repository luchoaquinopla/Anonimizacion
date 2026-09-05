"""Persistencia de `ErrorDocumento` en cuarentena (tasks.md 7.5, spec `batch-processing`).

`ErrorDocumento` (`dominio/errores.py`) SOLO tiene `id_documento`, `etapa`,
`codigo` -- por diseño, nunca un mensaje crudo ni contenido del documento
(ver el docstring de ese módulo, y design.md "Sin PII en cola, logs ni
DLQ"). `EscritorCuarentena` es una capa de persistencia deliberadamente
angosta: no acepta nada más que un `ErrorDocumento`, así que no hay forma de
que se filtre PII por este camino aunque quien lo llame lo intente.
"""

from __future__ import annotations

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import ErrorDocumento
from anonimizacion.salida.modelos_orm import Cuarentena


class EscritorCuarentena:
    """Escribe `ErrorDocumento` en la tabla `cuarentena` (ver `modelos_orm.py`)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def registrar(self, error: ErrorDocumento) -> None:
        """Inserta el apartado; reprocesar la misma corrida no duplica.

        Defecto ya mergeado que este método corrige: `cuarentena` no tenía
        ninguna restricción única (a diferencia de `estudio`, que sí tiene
        `uq_estudio_clave_documento`), así que un reintento de Celery sobre
        el mismo grupo duplicaba la fila y el reporte la contaba dos veces
        (ver `tests/web/test_reporte_cuarentena.py`, el test que reproduce el
        defecto contra el código sin guarda).

        La guarda es de DOS capas, calcada de
        `salida/destinos/postgres.py::escribir_registro`, y las dos hacen
        falta: el `SELECT` evita el trabajo en el caso normal, y la
        restricción única `(corrida_id, id_documento)` es la autoridad final
        ante la carrera que ese `SELECT` no cierra -- dos trabajadores pueden
        consultar antes de que ninguno haya commiteado. La consulta y la
        inserción van en la MISMA transacción a propósito: `sesion.scalar`
        abre una transacción implícita, así que separarlas en un
        `sesion.begin()` posterior explota con
        `InvalidRequestError: A transaction is already begun`.

        `_a_fallo` envuelve esta llamada en `except Exception: pass`
        (pipeline/ejecutor.py). Si la duplicación se manifestara como
        excepción propagada, sería indistinguible de una caída real de
        infraestructura -- el caso que alimenta la columna "sin desenlace"
        del embudo. Por eso el `IntegrityError` se resuelve ACÁ, no se deja
        subir.

        Un `ErrorDocumento` sin `corrida_id` (`None`) conserva el
        comportamiento anterior e inserta siempre: `NULL` no colisiona con
        `NULL` en la restricción única, así que sin corrida no hay garantía
        de idempotencia (design.md, Decisión 4) -- mismo precedente que
        `clave_documento` en `estudio`.
        """
        with Session(self._engine) as sesion:
            try:
                # Consulta e insercion en LA MISMA transaccion: separarlas
                # ampliaria la ventana de la carrera sin ganar nada.
                with sesion.begin():
                    if self._ya_registrado(sesion, error):
                        return
                    self._insertar(error, sesion)
            except IntegrityError:
                # Carrera: otro trabajador registro el mismo (corrida_id,
                # id_documento) entre nuestra consulta y nuestra insercion.
                # La restriccion unica es la autoridad final; el apartado ya
                # esta escrito y no hay nada que hacer.
                pass

    @staticmethod
    def _ya_registrado(sesion: Session, error: ErrorDocumento) -> bool:
        if error.corrida_id is None:
            return False
        return (
            sesion.scalar(
                select(Cuarentena.id).where(
                    Cuarentena.corrida_id == error.corrida_id,
                    Cuarentena.id_documento == error.id_documento,
                )
            )
            is not None
        )

    @staticmethod
    def _insertar(error: ErrorDocumento, sesion: Session) -> None:
        sesion.add(
            Cuarentena(
                id_documento=error.id_documento,
                etapa=error.etapa,
                codigo=error.codigo.value,
                campo=error.campo,
                pagina=error.pagina,
                tipo_documento=error.tipo_documento.value if error.tipo_documento else None,
                tamano_bytes=error.tamano_bytes,
                tope_bytes=error.tope_bytes,
                corrida_id=error.corrida_id,
            )
        )
