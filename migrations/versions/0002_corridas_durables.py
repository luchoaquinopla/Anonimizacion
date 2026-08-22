"""agrega persistencia durable para corridas y documentos inventariados.

Revision ID: 0002_corridas_durables
Revises: 0001_esquema_inicial
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_corridas_durables"
down_revision: Union[str, None] = "0001_esquema_inicial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corrida",
        sa.Column("id_corrida", sa.String(36), primary_key=True),
        sa.Column("estado", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("actualizada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_corrida_estado", "corrida", ["estado"])
    op.create_table(
        "documento_corrida",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("corrida_id", sa.String(36), sa.ForeignKey("corrida.id_corrida"), nullable=False),
        sa.Column("huella_contenido", sa.String(64), nullable=False),
        sa.Column("ruta_autorizada", sa.String(), nullable=False),
        sa.Column("estado", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("actualizada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("corrida_id", "huella_contenido", name="uq_documento_corrida_huella"),
    )
    op.create_index("ix_documento_corrida_corrida_id", "documento_corrida", ["corrida_id"])
    op.create_index("ix_documento_corrida_estado", "documento_corrida", ["estado"])


def downgrade() -> None:
    op.drop_table("documento_corrida")
    op.drop_table("corrida")
