"""Agrega la tabla estudio (fecha y hora por documento) y su FK en las mediciones.

Motivo: `episodio.fecha_ancla` es la fecha del GRUPO (ventana +-7 dias), no la de
cada estudio. Sin esta tabla, el delta entre el ECG y el laboratorio de un mismo
episodio no es computable en SQL ni siquiera a granularidad de dia.

`hora_estudio` es TIME WITHOUT TIME ZONE: los documentos no declaran huso y no se
infiere ninguno. `precision_hora` viaja como dato propio porque no es derivable
del valor almacenado (ver `dominio/precision_hora.py`).

Revision ID: 0006_estudio_y_hora
Revises: 0005_tamano_y_tope_cuarentena
Create Date: 2026-08-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_estudio_y_hora"
down_revision: Union[str, None] = "0005_tamano_y_tope_cuarentena"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLAS_CON_MEDICIONES = ("medicion_ecg", "resultado_laboratorio", "medicion_eco")


def upgrade() -> None:
    op.create_table(
        "estudio",
        sa.Column("id_estudio", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id_episodio", sa.String(length=64), nullable=False),
        sa.Column("tipo_documento", sa.String(), nullable=False),
        sa.Column("fecha_estudio", sa.Date(), nullable=False),
        sa.Column("hora_estudio", sa.Time(), nullable=True),
        sa.Column("precision_hora", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["id_episodio"], ["episodio.id_episodio"]),
    )
    op.create_index("ix_estudio_id_episodio", "estudio", ["id_episodio"])

    # SQLite no soporta ALTER TABLE para agregar una FK y la suite corre contra
    # SQLite: `batch_alter_table` recrea la tabla en vez de emitir el ALTER.
    for tabla in _TABLAS_CON_MEDICIONES:
        with op.batch_alter_table(tabla) as lote:
            lote.add_column(sa.Column("id_estudio", sa.Integer(), nullable=True))
            lote.create_foreign_key(
                f"fk_{tabla}_id_estudio", "estudio", ["id_estudio"], ["id_estudio"]
            )
            lote.create_index(f"ix_{tabla}_id_estudio", ["id_estudio"])


def downgrade() -> None:
    """Revertir descarta la fecha y la hora por estudio ya persistidas.

    Las mediciones y los episodios sobreviven, pero el momento de cada documento
    se pierde: recuperarlo exige reprocesar los originales desde `cuarentena`/
    almacenamiento cifrado. (La proyección Parquet que conservaba los mismos
    campos como respaldo de lectura se eliminó en
    `chore/resolver-codigo-desconectado`: no tenía llamador de producción.)
    """
    for tabla in _TABLAS_CON_MEDICIONES:
        with op.batch_alter_table(tabla) as lote:
            lote.drop_index(f"ix_{tabla}_id_estudio")
            lote.drop_constraint(f"fk_{tabla}_id_estudio", type_="foreignkey")
            lote.drop_column("id_estudio")

    op.drop_index("ix_estudio_id_episodio", table_name="estudio")
    op.drop_table("estudio")
