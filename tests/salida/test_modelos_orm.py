"""Pruebas del DDL de `salida/modelos_orm.py` contra SQLite en memoria.

Foco de estas pruebas: la tabla `estudio`, que existe porque ninguna otra tabla
guardaba fecha por documento -- la única fecha en SQL era `episodio.fecha_ancla`,
que es la ventana ±7 días completa. Sin `estudio`, el delta entre dos estudios
del mismo episodio no es computable en SQL ni siquiera a granularidad de día.
"""
from __future__ import annotations

from datetime import date, time

import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.salida.modelos_orm import (
    Base,
    Episodio,
    Estudio,
    MedicionEcg,
    MedicionEco,
    ResultadoLaboratorio,
)

_ID_EPISODIO = "a" * 64
_ID_PACIENTE = "b" * 64


def _motor_en_memoria() -> sa.Engine:
    motor = sa.create_engine("sqlite://")
    Base.metadata.create_all(motor)
    return motor


def _sembrar_episodio(sesion: Session) -> None:
    sesion.add(Episodio(id_episodio=_ID_EPISODIO, id_paciente=_ID_PACIENTE, fecha_ancla=date(2024, 3, 4)))


def test_estudio_persiste_fecha_hora_y_precision() -> None:
    motor = _motor_en_memoria()

    with Session(motor) as sesion, sesion.begin():
        _sembrar_episodio(sesion)
        sesion.add(
            Estudio(
                id_episodio=_ID_EPISODIO,
                tipo_documento="ecg",
                fecha_estudio=date(2024, 3, 4),
                hora_estudio=time(10, 32, 15),
                precision_hora=PrecisionHora.SEGUNDO.value,
            )
        )

    with Session(motor) as sesion:
        estudio = sesion.scalars(sa.select(Estudio)).one()
        assert estudio.fecha_estudio == date(2024, 3, 4)
        assert estudio.hora_estudio == time(10, 32, 15)
        assert estudio.precision_hora == "segundo"


def test_estudio_sin_hora_guarda_null_y_precision_ausente() -> None:
    """Un documento que no trae hora nunca recibe medianoche por defecto."""
    motor = _motor_en_memoria()

    with Session(motor) as sesion, sesion.begin():
        _sembrar_episodio(sesion)
        sesion.add(
            Estudio(
                id_episodio=_ID_EPISODIO,
                tipo_documento="ecocardiograma",
                fecha_estudio=date(2024, 3, 4),
                hora_estudio=None,
                precision_hora=PrecisionHora.AUSENTE.value,
            )
        )

    with Session(motor) as sesion:
        estudio = sesion.scalars(sa.select(Estudio)).one()
        assert estudio.hora_estudio is None
        assert estudio.precision_hora == "ausente"


def test_mediciones_aceptan_id_estudio_nullable() -> None:
    """La FK es aditiva: las filas previas al cambio siguen siendo válidas sin ella."""
    motor = _motor_en_memoria()

    with Session(motor) as sesion, sesion.begin():
        _sembrar_episodio(sesion)
        sesion.add(MedicionEcg(id_episodio=_ID_EPISODIO))
        sesion.add(ResultadoLaboratorio(id_episodio=_ID_EPISODIO, analito="Potasio", seccion="ionograma"))
        sesion.add(MedicionEco(id_episodio=_ID_EPISODIO))

    with Session(motor) as sesion:
        assert sesion.scalars(sa.select(MedicionEcg)).one().id_estudio is None
        assert sesion.scalars(sa.select(ResultadoLaboratorio)).one().id_estudio is None
        assert sesion.scalars(sa.select(MedicionEco)).one().id_estudio is None


def test_mediciones_enlazan_con_el_estudio_que_las_origino() -> None:
    motor = _motor_en_memoria()

    with Session(motor) as sesion, sesion.begin():
        _sembrar_episodio(sesion)
        estudio = Estudio(
            id_episodio=_ID_EPISODIO,
            tipo_documento="ecg",
            fecha_estudio=date(2024, 3, 4),
            hora_estudio=time(10, 32, 15),
            precision_hora=PrecisionHora.SEGUNDO.value,
        )
        sesion.add(estudio)
        sesion.flush()
        sesion.add(MedicionEcg(id_episodio=_ID_EPISODIO, id_estudio=estudio.id_estudio))

    with Session(motor) as sesion:
        id_estudio = sesion.scalars(sa.select(Estudio.id_estudio)).one()
        assert sesion.scalars(sa.select(MedicionEcg)).one().id_estudio == id_estudio
