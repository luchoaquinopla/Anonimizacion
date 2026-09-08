"""Agrega marca de completitud (completo, campos_no_extraidos) a estudio.

Requisito "que un campo nuevo no rompa el parseo, sino que sea un aviso" --
ver `dominio/errores.py::CodigoErrorDocumento.CAMPO_NO_EXTRAIDO` y
`dominio/modelos.py::RegistroAnonimizado.campos_no_extraidos`. Ambas columnas
nacen NULLABLE, sin backfill: las filas escritas antes de este cambio no
tienen forma de saber si estaban completas -- releerlas exigiría volver a
reconciliar el documento original, que ya no está disponible en esta etapa
del pipeline -- y `NULL` es la verdad ("no se sabe"), no `True` inventado.
Mismo criterio que `ruta_autorizada` en `corrida` (migración `0011`) y
`creado_en` en `estudio` (migración `0008`). Las filas nuevas del pipeline
siempre completan ambas columnas (`destinos/postgres.py::_insertar`).

`campos_no_extraidos` es JSON portable (mismo patrón que `adicionales`/
`unidades` en `0001_esquema_inicial`): lista de `id_campo` de vocabulario
cerrado, nunca texto libre ni contenido del documento.

Revision ID: 0012_completitud_en_estudio
Revises: 0011_ruta_autorizada_en_corrida
Create Date: 2026-09-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0012_completitud_en_estudio"
down_revision: Union[str, None] = "0011_ruta_autorizada_en_corrida"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_PORTABLE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("estudio") as lote:
        lote.add_column(sa.Column("completo", sa.Boolean(), nullable=True))
        lote.add_column(sa.Column("campos_no_extraidos", _JSON_PORTABLE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("estudio") as lote:
        lote.drop_column("campos_no_extraidos")
        lote.drop_column("completo")
