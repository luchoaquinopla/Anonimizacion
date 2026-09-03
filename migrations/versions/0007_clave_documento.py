"""Agrega estudio.clave_documento con restriccion unica (reprocesar no duplica).

La identidad del documento es un HMAC del sha256 con el pepper, nunca la huella
cruda: publicarla permitiria a cualquiera con el PDF original probar que ese
documento esta en el corpus.

La columna nace opcional y sin relleno hacia atras. `NULL` no colisiona con
`NULL` en una restriccion unica, ni en SQLite ni en Postgres, asi que las filas
escritas antes de este cambio conviven sin romper nada -- pero tampoco quedan
protegidas contra duplicacion, porque su clave no puede derivarse sin releer el
documento original.

Revision ID: 0007_clave_documento
Revises: 0006_estudio_y_hora
Create Date: 2026-08-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_clave_documento"
down_revision: Union[str, None] = "0006_estudio_y_hora"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite no soporta agregar una restriccion UNIQUE con ALTER TABLE directo y
    # la suite corre contra SQLite: `batch_alter_table` recrea la tabla.
    with op.batch_alter_table("estudio") as lote:
        lote.add_column(sa.Column("clave_documento", sa.String(length=32), nullable=True))
        lote.create_unique_constraint("uq_estudio_clave_documento", ["clave_documento"])


def downgrade() -> None:
    """Revertir descarta las claves de documento ya persistidas.

    No se pierde ningun dato clinico: mediciones, episodios y estudios quedan
    intactos. Lo que se pierde es la capacidad de reconocer un reprocesamiento,
    de modo que volver a correr el corpus despues de revertir vuelve a duplicar.
    """
    with op.batch_alter_table("estudio") as lote:
        lote.drop_constraint("uq_estudio_clave_documento", type_="unique")
        lote.drop_column("clave_documento")
