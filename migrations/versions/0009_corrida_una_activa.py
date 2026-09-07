"""Gate de "una corrida a la vez" a nivel de base: columna `activa` + índice único parcial.

Revisión adversarial ronda 3, hallazgo 4 (feature `despachador-desde-el-panel`):
el `threading.Lock` de `ServicioCorridasReal.crear_corrida` sólo protege al
panel contra SUS PROPIAS peticiones concurrentes -- confirmado que
`scripts/procesar_carpeta.py` no llama `listar_corridas_no_terminales` en
ningún punto, así que no tiene ningún gate propio. Dos corridas reales
(panel + CLI) podían convivir sin que nada las detectara hasta agotar la
memoria (~875 MB por proceso hijo de `MotorPii`, multiplicado por
`procesos` en cada una).

`activa` (`Boolean`, `NOT NULL`) es `True` mientras `corrida.estado` NO es
terminal (`completada`, `completada_con_cuarentena`, `fallida`) --
`RepositorioCorridas` la mantiene sincronizada en cada escritura de
`estado`, nunca se setea a mano fuera de ahí. El índice único parcial
`ux_corrida_una_activa` (`WHERE activa`) hace que la BASE rechace crear una
segunda fila `activa=True` mientras ya existe una -- Postgres decide
atómicamente, sin importar qué proceso ni en qué orden llame `lanzar()`.
Las filas `activa=False` (terminales) quedan fuera del índice parcial:
nunca compiten entre sí, así que puede haber cualquier cantidad de corridas
CERRADAS sin que el índice les preste atención -- sólo puede existir UNA
fila `activa=True` en total.

`LanzadorCorrida.lanzar()` traduce la violación de esta restricción
(`IntegrityError`) a `CorridaEnCursoError` -- ver `ingesta/lanzador_corrida.py`.

Backfill: toda fila existente se marca `activa` según su `estado` actual en
el momento de esta migración -- no se puede saber si una corrida vieja en un
estado no terminal sigue genuinamente en curso, pero es la misma pregunta
que ya resuelve `RepositorioCorridas.ultima_actividad`/`recuperar_corridas_abandonadas`
al arrancar el panel, no una nueva.

Revision ID: 0009_corrida_una_activa
Revises: 0008_corrida_en_salida
Create Date: 2026-09-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_corrida_una_activa"
down_revision: Union[str, None] = "0008_corrida_en_salida"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ESTADOS_TERMINALES = ("completada", "completada_con_cuarentena", "fallida")


def upgrade() -> None:
    # `server_default=sa.true()` para el backfill inicial: toda fila
    # existente nace `activa=True` (mismo criterio que el default de
    # `CorridaOrm.activa` en el modelo), y el UPDATE siguiente corrige a
    # `False` sólo las que ya están en un estado terminal -- las corridas
    # sin cerrar de antes de esta migración quedan `activa=True`, sujetas al
    # mismo índice único parcial que cualquier corrida nueva.
    with op.batch_alter_table("corrida") as lote:
        lote.add_column(sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()))

    corrida = sa.table("corrida", sa.column("estado", sa.String), sa.column("activa", sa.Boolean))
    op.execute(corrida.update().where(corrida.c.estado.in_(_ESTADOS_TERMINALES)).values(activa=False))

    op.create_index(
        "ux_corrida_una_activa",
        "corrida",
        ["activa"],
        unique=True,
        sqlite_where=sa.text("activa"),
        postgresql_where=sa.text("activa"),
    )


def downgrade() -> None:
    """Revertir descarta el gate a nivel de base -- vuelve a depender sólo
    del `threading.Lock` de `ServicioCorridasReal` (protección parcial, ver
    el docstring de arriba). No se pierde ningún dato de `corrida`: sólo la
    columna `activa`, que es puramente derivada de `estado`."""
    op.drop_index("ux_corrida_una_activa", table_name="corrida")
    with op.batch_alter_table("corrida") as lote:
        lote.drop_column("activa")
