"""Agrega corrida_id a estudio y cuarentena, con la unicidad que a cuarentena le faltaba.

`corrida_id` viaja como dato desde el mensaje de cola hasta `estudio` y
`cuarentena` (design.md, Decisión 1 y 2). Va SOLO a esas dos tablas: `episodio`
puede completarse en dos corridas y las tablas de medición cuelgan de
`estudio.id_estudio` (Decisión 3). Sin claves foráneas hacia `corrida`,
deliberadamente: la tabla `corrida` es plano de control, `estudio` y
`cuarentena` son plano de datos, y una FK obligaría a que exista una fila de
corrida para escribir salida clínica -- falso para el script sin corrida, los
tests, y la cuarentena que `FuenteLocal` escribe por sobretamaño antes de que
exista ninguna corrida.

`cuarentena` gana la restricción única `(corrida_id, id_documento)` que
`estudio` ya tenía (`uq_estudio_clave_documento`, migración 0007): hoy no
existe ninguna, y un reintento de Celery sobre el mismo grupo duplica el
apartado (design.md, Decisión 4 y 9). Los `NULL` no colisionan entre sí ni en
SQLite ni en Postgres, así que la restricción se crea sobre duplicados
preexistentes SIN deduplicar ni rellenar nada -- las filas de antes de este
cambio quedan exactamente como estaban, sin garantía de idempotencia, igual
que `estudio.clave_documento`.

`ix_documento_corrida_corrida_id` se elimina: es estrictamente redundante con
`uq_documento_corrida_huella (corrida_id, huella_contenido)`, que ya cubre
cualquier consulta por prefijo `corrida_id`, y se paga en cada una de las
inserciones del inventario.

Revision ID: 0008_corrida_en_salida
Revises: 0007_clave_documento
Create Date: 2026-09-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_corrida_en_salida"
down_revision: Union[str, None] = "0007_clave_documento"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite no soporta agregar una restriccion UNIQUE con ALTER TABLE directo
    # y la suite corre contra SQLite: `batch_alter_table` recrea la tabla.
    # Se usa tambien en `estudio` por coherencia con 0007, aunque agregar
    # columnas nullable ahi no lo exigiria.
    with op.batch_alter_table("estudio") as lote:
        lote.add_column(sa.Column("corrida_id", sa.String(length=36), nullable=True))
        # `NULL` = "no se sabe cuando" para las filas de antes de este cambio,
        # que es la verdad -- un `server_default` las dataria con el momento
        # de la migracion, y eso seria una mentira.
        lote.add_column(sa.Column("creado_en", sa.DateTime(timezone=True), nullable=True))
        lote.create_index("ix_estudio_corrida_creado", ["corrida_id", "creado_en"])

    with op.batch_alter_table("cuarentena") as lote:
        lote.add_column(sa.Column("corrida_id", sa.String(length=36), nullable=True))
        lote.create_unique_constraint(
            "uq_cuarentena_corrida_documento", ["corrida_id", "id_documento"]
        )
        lote.create_index("ix_cuarentena_corrida_creado", ["corrida_id", "creado_en"])

    with op.batch_alter_table("documento_corrida") as lote:
        lote.drop_index("ix_documento_corrida_corrida_id")


def downgrade() -> None:
    """Revertir descarta la atribucion por corrida de estudio y cuarentena.

    Con ella se pierde la idempotencia de cuarentena: sin la restriccion
    unica, reprocesar vuelve a duplicar el apartado. No se pierde ningun dato
    clinico: mediciones, episodios y estudios quedan intactos.
    """
    with op.batch_alter_table("documento_corrida") as lote:
        lote.create_index("ix_documento_corrida_corrida_id", ["corrida_id"])

    with op.batch_alter_table("cuarentena") as lote:
        lote.drop_index("ix_cuarentena_corrida_creado")
        lote.drop_constraint("uq_cuarentena_corrida_documento", type_="unique")
        lote.drop_column("corrida_id")

    with op.batch_alter_table("estudio") as lote:
        lote.drop_index("ix_estudio_corrida_creado")
        lote.drop_column("creado_en")
        lote.drop_column("corrida_id")
