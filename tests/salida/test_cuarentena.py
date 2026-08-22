"""Tests de `salida/cuarentena.py` (tasks.md 7.5, spec `batch-processing`).

`EscritorCuarentena` persiste `ErrorDocumento` -- por construcción, ese
dataclass SOLO tiene `id_documento`, `etapa`, `codigo` (ver
`dominio/errores.py`); no hay forma de que un mensaje crudo o contenido del
documento llegue acá, porque `ErrorDocumento` no los tiene como campos.
"""

from __future__ import annotations

import sqlalchemy as sa

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.modelos_orm import Base, Cuarentena


def _motor():
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def test_registrar_persiste_id_documento_etapa_y_codigo() -> None:
    motor = _motor()
    escritor = EscritorCuarentena(motor)
    error = ErrorDocumento(id_documento="doc-1", etapa="parseo", codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO)

    escritor.registrar(error)

    with sa.orm.Session(motor) as sesion:
        filas = sesion.scalars(sa.select(Cuarentena)).all()

    assert len(filas) == 1
    assert filas[0].id_documento == "doc-1"
    assert filas[0].etapa == "parseo"
    assert filas[0].codigo == "parseo_incompleto"
    assert filas[0].creado_en is not None


def test_registrar_varios_errores_los_acumula() -> None:
    motor = _motor()
    escritor = EscritorCuarentena(motor)

    escritor.registrar(ErrorDocumento("doc-1", "parseo", CodigoErrorDocumento.PARSEO_INCOMPLETO))
    escritor.registrar(ErrorDocumento("doc-2", "pseudonimizacion", CodigoErrorDocumento.CLAVE_PII_AMBIGUA))

    with sa.orm.Session(motor) as sesion:
        filas = sesion.scalars(sa.select(Cuarentena)).all()

    assert len(filas) == 2
    assert {fila.id_documento for fila in filas} == {"doc-1", "doc-2"}


def test_registrar_persiste_solo_metadata_segura_de_reconciliacion() -> None:
    motor = _motor()
    escritor = EscritorCuarentena(motor)
    escritor.registrar(
        ErrorDocumento(
            "doc-1",
            "reconciliacion",
            CodigoErrorDocumento.COBERTURA_INCOMPLETA,
            campo="ecg.vent_rate",
            pagina=2,
        )
    )

    with sa.orm.Session(motor) as sesion:
        fila = sesion.scalars(sa.select(Cuarentena)).one()

    assert (fila.id_documento, fila.etapa, fila.codigo, fila.campo, fila.pagina) == (
        "doc-1",
        "reconciliacion",
        "cobertura_incompleta",
        "ecg.vent_rate",
        2,
    )
    assert set(Cuarentena.__table__.columns.keys()) == {
        "id",
        "id_documento",
        "etapa",
        "codigo",
        "campo",
        "pagina",
        "tipo_documento",
        "creado_en",
    }


def test_registrar_persiste_tipo_documento_seguro() -> None:
    from anonimizacion.dominio.tipos_documento import TipoDocumento

    motor = _motor()
    EscritorCuarentena(motor).registrar(
        ErrorDocumento("doc-1", "parseo", CodigoErrorDocumento.PARSEO_INCOMPLETO, tipo_documento=TipoDocumento.LABORATORIO)
    )

    with sa.orm.Session(motor) as sesion:
        fila = sesion.scalars(sa.select(Cuarentena)).one()

    assert fila.tipo_documento == "laboratorio"
