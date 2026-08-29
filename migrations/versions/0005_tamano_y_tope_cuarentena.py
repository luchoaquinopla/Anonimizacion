"""Agrega tamano_bytes y tope_bytes seguros a cuarentena (sobretamano).

Revision ID: 0005_tamano_y_tope_cuarentena
Revises: 0004_fusion_corridas_cuarentena
Create Date: 2026-08-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_tamano_y_tope_cuarentena"
down_revision: Union[str, None] = "0004_fusion_corridas_cuarentena"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cuarentena", sa.Column("tamano_bytes", sa.Integer(), nullable=True))
    op.add_column("cuarentena", sa.Column("tope_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cuarentena", "tope_bytes")
    op.drop_column("cuarentena", "tamano_bytes")
