"""esquema inicial: vinculo_paciente, episodio, medicion_ecg, resultado_laboratorio, medicion_eco, texto_seccion_eco, cuarentena

Revision ID: 0001_esquema_inicial
Revises:
Create Date: 2026-08-16

DDL escrito a mano (no autogenerado) para que sea determinístico y
revisable sin necesitar un Postgres real corriendo (ver
`anonimizacion.salida.modelos_orm` para el detalle de cada tabla y el
razonamiento ancha/larga por tabla, ya explicado ahí para no duplicarlo).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001_esquema_inicial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LONGITUD_CLAVE_HEX = 32
_JSON_PORTABLE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "vinculo_paciente",
        sa.Column("id_alt_paciente", sa.String(_LONGITUD_CLAVE_HEX), primary_key=True),
        sa.Column("id_paciente", sa.String(_LONGITUD_CLAVE_HEX), nullable=True),
        sa.Column("ambiguo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "episodio",
        sa.Column("id_episodio", sa.String(_LONGITUD_CLAVE_HEX), primary_key=True),
        sa.Column("id_paciente", sa.String(_LONGITUD_CLAVE_HEX), nullable=False),
        sa.Column("fecha_ancla", sa.Date(), nullable=False),
    )
    op.create_index("ix_episodio_id_paciente", "episodio", ["id_paciente"])

    op.create_table(
        "medicion_ecg",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "id_episodio",
            sa.String(_LONGITUD_CLAVE_HEX),
            sa.ForeignKey("episodio.id_episodio"),
            nullable=False,
        ),
        sa.Column("id_medico", sa.String(_LONGITUD_CLAVE_HEX), nullable=True),
        sa.Column("vent_rate", sa.String(), nullable=True),
        sa.Column("pr_interval", sa.String(), nullable=True),
        sa.Column("qrs_duration", sa.String(), nullable=True),
        sa.Column("qt_qtc", sa.String(), nullable=True),
        sa.Column("ejes", sa.String(), nullable=True),
        sa.Column("adicionales", _JSON_PORTABLE, nullable=True),
    )
    op.create_index("ix_medicion_ecg_id_episodio", "medicion_ecg", ["id_episodio"])

    op.create_table(
        "resultado_laboratorio",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "id_episodio",
            sa.String(_LONGITUD_CLAVE_HEX),
            sa.ForeignKey("episodio.id_episodio"),
            nullable=False,
        ),
        sa.Column("id_medico", sa.String(_LONGITUD_CLAVE_HEX), nullable=True),
        sa.Column("analito", sa.String(), nullable=False),
        sa.Column("seccion", sa.String(), nullable=False),
        sa.Column("valor_num", sa.Float(), nullable=True),
        sa.Column("valor_texto", sa.String(), nullable=True),
        sa.Column("unidad", sa.String(), nullable=True),
        sa.Column("ref_min", sa.Float(), nullable=True),
        sa.Column("ref_max", sa.Float(), nullable=True),
    )
    op.create_index("ix_resultado_laboratorio_id_episodio", "resultado_laboratorio", ["id_episodio"])

    op.create_table(
        "medicion_eco",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "id_episodio",
            sa.String(_LONGITUD_CLAVE_HEX),
            sa.ForeignKey("episodio.id_episodio"),
            nullable=False,
        ),
        sa.Column("id_medico_solicitante", sa.String(_LONGITUD_CLAVE_HEX), nullable=True),
        sa.Column("id_medico_informante", sa.String(_LONGITUD_CLAVE_HEX), nullable=True),
        sa.Column("id_matricula_informante", sa.String(_LONGITUD_CLAVE_HEX), nullable=True),
        sa.Column("ao", sa.String(), nullable=True),
        sa.Column("ai", sa.String(), nullable=True),
        sa.Column("ddvi", sa.String(), nullable=True),
        sa.Column("dsvi", sa.String(), nullable=True),
        sa.Column("fa", sa.String(), nullable=True),
        sa.Column("septum", sa.String(), nullable=True),
        sa.Column("p_posterior", sa.String(), nullable=True),
        sa.Column("unidades", _JSON_PORTABLE, nullable=True),
        sa.Column("adicionales", _JSON_PORTABLE, nullable=True),
    )
    op.create_index("ix_medicion_eco_id_episodio", "medicion_eco", ["id_episodio"])

    op.create_table(
        "texto_seccion_eco",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "id_episodio",
            sa.String(_LONGITUD_CLAVE_HEX),
            sa.ForeignKey("episodio.id_episodio"),
            nullable=False,
        ),
        sa.Column("seccion", sa.String(), nullable=False),
        sa.Column("texto", sa.String(), nullable=False),
    )
    op.create_index("ix_texto_seccion_eco_id_episodio", "texto_seccion_eco", ["id_episodio"])

    op.create_table(
        "cuarentena",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id_documento", sa.String(), nullable=False),
        sa.Column("etapa", sa.String(), nullable=False),
        sa.Column("codigo", sa.String(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cuarentena_id_documento", "cuarentena", ["id_documento"])


def downgrade() -> None:
    op.drop_table("cuarentena")
    op.drop_table("texto_seccion_eco")
    op.drop_table("medicion_eco")
    op.drop_table("resultado_laboratorio")
    op.drop_table("medicion_ecg")
    op.drop_table("episodio")
    op.drop_table("vinculo_paciente")
