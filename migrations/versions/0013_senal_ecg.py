"""Crea `senal_ecg` (design.md `senal-ecg-y-dataset-vinculado`, decisión 3).

PK = FK `id_estudio` (`ON DELETE CASCADE`): la señal es un satélite estricto
del estudio, nunca existe sin él y siempre lo acompaña 1:1. `SET STORAGE
EXTERNAL` (sólo Postgres -- SQLite no tiene el concepto) desactiva
compresión TOAST para `muestras_uv`/`mascara`: ya llegan comprimidas por
`salida/codec_senal.py` (zlib), y comprimir dos veces sólo gasta CPU sin
bajar tamaño. No hay backfill: la tabla nace vacía, ningún estudio previo a
este cambio puede recuperar su señal sin volver a leer el PDF original.

`version_formato` (WARNING, revisión adversarial): versión del ESQUEMA
BINARIO de `salida/codec_senal.py` (layout de bytes: int16 LE + zlib /
packbits + zlib), no del algoritmo de extracción -- ver
`version_extractor` más abajo y el docstring de `codec_senal.py`. `NOT
NULL DEFAULT 1`: la tabla nace vacía en esta misma migración, así que el
default cubre cualquier fila que se escriba desde ahora, sin ambigüedad de
"no se sabe" como en otras columnas legadas de este repo.

`version_extractor` (columna ya presente en `SenalEcg.version_extractor`,
`dominio/senal_ecg.py`): versión del ALGORITMO que reconstruye la señal a
partir de los trazos vectoriales (`extraccion/senal_ecg.py`) -- pregunta
independiente de `version_formato`: cómo se calculó el valor vs. cómo se
empaquetaron sus bytes.

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
        sa.Column("version_formato", sa.Integer(), nullable=False, server_default="1"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE senal_ecg ALTER COLUMN muestras_uv SET STORAGE EXTERNAL")
        op.execute("ALTER TABLE senal_ecg ALTER COLUMN mascara SET STORAGE EXTERNAL")


def downgrade() -> None:
    op.drop_table("senal_ecg")
