"""Persistencia de `ErrorDocumento` en cuarentena (tasks.md 7.5, spec `batch-processing`).

`ErrorDocumento` (`dominio/errores.py`) SOLO tiene `id_documento`, `etapa`,
`codigo` -- por diseño, nunca un mensaje crudo ni contenido del documento
(ver el docstring de ese módulo, y design.md "Sin PII en cola, logs ni
DLQ"). `EscritorCuarentena` es una capa de persistencia deliberadamente
angosta: no acepta nada más que un `ErrorDocumento`, así que no hay forma de
que se filtre PII por este camino aunque quien lo llame lo intente.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import ErrorDocumento
from anonimizacion.salida.modelos_orm import Cuarentena


class EscritorCuarentena:
    """Escribe `ErrorDocumento` en la tabla `cuarentena` (ver `modelos_orm.py`)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def registrar(self, error: ErrorDocumento) -> None:
        with Session(self._engine) as sesion, sesion.begin():
            sesion.add(
                Cuarentena(
                    id_documento=error.id_documento,
                    etapa=error.etapa,
                    codigo=error.codigo.value,
                    campo=error.campo,
                    pagina=error.pagina,
                    tipo_documento=error.tipo_documento.value if error.tipo_documento else None,
                )
            )
