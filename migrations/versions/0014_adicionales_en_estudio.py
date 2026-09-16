"""Agrega estudio.adicionales y elimina medicion_ecg.adicionales.

Hallazgo (entrega 2b, corrección post-entrega-2): `_escribir_laboratorio` y
`_escribir_eco` (`salida/destinos/postgres.py`) nunca persistían
`registro.adicionales` -- sólo `_escribir_ecg` lo hacía, en
`medicion_ecg.adicionales`. Eso descartaba en silencio cuasi-identificadores
que la decisión de comité 2026-09-07 exige conservar para los 3 tipos: edad
(laboratorio, eco), peso/altura/superficie_corporal (eco), origen
(laboratorio). Ver `openspec/changes/senal-ecg-y-dataset-vinculado/tasks.md`,
sección "Entrega 2b".

`estudio.adicionales` reemplaza a `medicion_ecg.adicionales` como destino
único de los adicionales de HEADER, para los 3 tipos de documento --
`medicion_eco.adicionales` NO se toca (sigue guardando las medidas del
CUERPO sin pivote, un dato distinto; ver docstring de `MedicionEco` en
`modelos_orm.py`). Se auditó con `rg` cada lector de
`MedicionEcg.adicionales`: sólo el escritor de este mismo módulo y los tests
de `tests/salida/` lo tocan -- ningún panel, embudo ni reporte de producción
lo lee. Por eso la columna se ELIMINA en vez de conservarla duplicada.

Copia de datos: no hay base de producción todavía, pero SÍ pueden existir
bases de prueba/desarrollo con filas ya escritas por la entrega 2 (PR #46).
El `UPDATE ... FROM` de abajo copia `medicion_ecg.adicionales` a
`estudio.adicionales` ANTES de borrar la columna, para no perder esos datos
en ninguna base existente.

Revision ID: 0014_adicionales_en_estudio
Revises: 0013_senal_ecg
Create Date: 2026-09-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014_adicionales_en_estudio"
down_revision: Union[str, None] = "0013_senal_ecg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_PORTABLE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("estudio") as lote:
        lote.add_column(sa.Column("adicionales", _JSON_PORTABLE, nullable=True))

    # Copia medicion_ecg.adicionales -> estudio.adicionales para filas ya
    # escritas (bases de prueba/desarrollo de la entrega 2). `UPDATE ... FROM`
    # es sintaxis Postgres; SQLite no la soporta, así que usa la subconsulta
    # correlacionada equivalente -- cada rama se prueba por separado contra
    # su propio motor en `test_migraciones.py` (no hay comparación cruzada
    # entre dialectos, cada test corre contra uno solo).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "UPDATE estudio SET adicionales = medicion_ecg.adicionales "
            "FROM medicion_ecg "
            "WHERE medicion_ecg.id_estudio = estudio.id_estudio "
            "AND medicion_ecg.adicionales IS NOT NULL"
        )
    else:
        op.execute(
            "UPDATE estudio SET adicionales = ("
            "SELECT medicion_ecg.adicionales FROM medicion_ecg "
            "WHERE medicion_ecg.id_estudio = estudio.id_estudio"
            ") WHERE EXISTS ("
            "SELECT 1 FROM medicion_ecg "
            "WHERE medicion_ecg.id_estudio = estudio.id_estudio "
            "AND medicion_ecg.adicionales IS NOT NULL"
            ")"
        )

    with op.batch_alter_table("medicion_ecg") as lote:
        lote.drop_column("adicionales")


def downgrade() -> None:
    with op.batch_alter_table("medicion_ecg") as lote:
        lote.add_column(sa.Column("adicionales", _JSON_PORTABLE, nullable=True))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "UPDATE medicion_ecg SET adicionales = estudio.adicionales "
            "FROM estudio "
            "WHERE estudio.id_estudio = medicion_ecg.id_estudio "
            "AND estudio.adicionales IS NOT NULL"
        )
    else:
        op.execute(
            "UPDATE medicion_ecg SET adicionales = ("
            "SELECT estudio.adicionales FROM estudio "
            "WHERE estudio.id_estudio = medicion_ecg.id_estudio"
            ") WHERE EXISTS ("
            "SELECT 1 FROM estudio "
            "WHERE estudio.id_estudio = medicion_ecg.id_estudio "
            "AND estudio.adicionales IS NOT NULL"
            ")"
        )

    with op.batch_alter_table("estudio") as lote:
        lote.drop_column("adicionales")
