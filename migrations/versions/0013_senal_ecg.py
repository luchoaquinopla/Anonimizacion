"""Crea `senal_ecg` (design.md `senal-ecg-y-dataset-vinculado`, decisión 3).

PK = FK `id_estudio` (`ON DELETE CASCADE`): la señal es un satélite estricto
del estudio, nunca existe sin él y siempre lo acompaña 1:1. `SET STORAGE
EXTERNAL` (sólo Postgres -- SQLite no tiene el concepto) desactiva
compresión TOAST para `muestras_uv`/`mascara`: ya llegan comprimidas por
`salida/codec_senal.py` (zlib), y comprimir dos veces sólo gasta CPU sin
bajar tamaño. No hay backfill: la tabla nace vacía, ningún estudio previo a
este cambio puede recuperar su señal sin volver a leer el PDF original.

Revision ID: 0013_senal_ecg
Revises: 0012_completitud_en_estudio
Create Date: 2026-09-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_senal_ecg"
down_revision: Union[str, None] = "0012_completitud_en_estudio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "senal_ecg",
        sa.Column("id_estudio", sa.Integer(), sa.ForeignKey("estudio.id_estudio", ondelete="CASCADE"), primary_key=True),
        sa.Column("muestras_uv", sa.LargeBinary(), nullable=False),
        sa.Column("mascara", sa.LargeBinary(), nullable=False),
        sa.Column("frecuencia_hz", sa.Integer(), nullable=False),
        sa.Column("version_extractor", sa.Integer(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE senal_ecg ALTER COLUMN muestras_uv SET STORAGE EXTERNAL")
        op.execute("ALTER TABLE senal_ecg ALTER COLUMN mascara SET STORAGE EXTERNAL")


def downgrade() -> None:
    op.drop_table("senal_ecg")
