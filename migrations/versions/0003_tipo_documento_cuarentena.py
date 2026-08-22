"""Agrega tipo de documento seguro a cuarentena.

Revision ID: 0003_tipo_documento_cuarentena
Revises: 0002_metadata_segura_cuarentena
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_tipo_documento_cuarentena"
down_revision: Union[str, None] = "0002_metadata_segura_cuarentena"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cuarentena", sa.Column("tipo_documento", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("cuarentena", "tipo_documento")
