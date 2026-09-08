"""Agrega ruta_autorizada a corrida (feature reanudacion-de-corridas).

`LanzadorCorrida.lanzar` pasa a persistir la raíz autorizada que inventarió,
para que `reintentar_corrida` pueda reconstruirla y pasarla como `entrada` a
`despacho_paralelo.inicializar_trabajador` al reencolar los apartados
reintentables. Nullable, sin backfill: las corridas existentes no tienen
forma de saber qué raíz se usó, y NULL es la verdad ("no se sabe"), no un
valor inventado -- mismo criterio que `estudio.creado_en` en `0008`.

Revision ID: 0011_ruta_autorizada_en_corrida
Revises: 0010_detalle_parseo_cuarentena
Create Date: 2026-09-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_ruta_autorizada_en_corrida"
down_revision: Union[str, None] = "0010_detalle_parseo_cuarentena"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("corrida") as lote:
        lote.add_column(sa.Column("ruta_autorizada", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("corrida") as lote:
        lote.drop_column("ruta_autorizada")
