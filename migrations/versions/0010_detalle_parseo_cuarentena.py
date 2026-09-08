"""Agrega detalle_parseo (vocabulario cerrado) a cuarentena.

Revision ID: 0010_detalle_parseo_cuarentena
Revises: 0009_corrida_una_activa
Create Date: 2026-09-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_detalle_parseo_cuarentena"
down_revision: Union[str, None] = "0009_corrida_una_activa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cuarentena", sa.Column("detalle_parseo", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("cuarentena", "detalle_parseo")
