"""Une las ramas de corridas durables y metadata segura de cuarentena.

Revision ID: 0004_fusion_corridas_cuarentena
Revises: 0002_corridas_durables, 0003_tipo_documento_cuarentena
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "0004_fusion_corridas_cuarentena"
down_revision: Union[str, Sequence[str], None] = (
    "0002_corridas_durables",
    "0003_tipo_documento_cuarentena",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
