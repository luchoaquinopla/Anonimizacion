"""Persistencia de `ErrorDocumento` en cuarentena. `EscritorCuarentena` es deliberadamente
angosto (sólo acepta `ErrorDocumento`, nunca mensaje crudo ni contenido): no hay forma de que se filtre PII por este camino."""

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
        """Inserta el apartado; reprocesar la misma corrida no duplica (guarda de dos capas:
        SELECT + restricción única `(corrida_id, id_documento)`, misma transacción).
        Sin `corrida_id`, inserta siempre -- sin garantía de idempotencia.
        IntegrityError se resuelve acá: `_a_fallo` traga excepciones y se confundiría
        con una caída de infra."""
        with Session(self._engine) as sesion:
            try:
                # Consulta e inserción en la misma transacción: separarlas ampliaría la carrera sin ganar nada.
                with sesion.begin():
                    if self._ya_registrado(sesion, error):
                        return
                    self._insertar(error, sesion)
            except IntegrityError:
                # Carrera resuelta por la restricción única: el apartado ya está escrito.
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
                detalle_parseo=error.detalle_parseo.value if error.detalle_parseo else None,
            )
        )
