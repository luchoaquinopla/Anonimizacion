"""Agrega campo y página seguros a cuarentena.

Revision ID: 0002_metadata_segura_cuarentena
Revises: 0001_esquema_inicial
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_metadata_segura_cuarentena"
down_revision: Union[str, None] = "0001_esquema_inicial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cuarentena", sa.Column("campo", sa.String(), nullable=True))
    op.add_column("cuarentena", sa.Column("pagina", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("cuarentena", "pagina")
    op.drop_column("cuarentena", "campo")
