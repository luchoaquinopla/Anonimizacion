"""Tests de `construir_plan_reintento` (feature `reanudacion-de-corridas`).

La única definición de "este código es reintentable" vive en
`dominio.errores.es_reintentable` -- este módulo verifica que el plan la
consulta correctamente, nunca que la reimplementa.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from anonimizacion.dominio.corridas import Corrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base, Cuarentena, DocumentoCorridaOrm
from anonimizacion.web.reintento_corrida import construir_plan_reintento


def _motor() -> sa.Engine:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def _cuarentena(motor: sa.Engine, *, id_documento: str, codigo: str, corrida_id: str) -> None:
    with sa.orm.Session(motor) as sesion, sesion.begin():
        sesion.add(Cuarentena(id_documento=id_documento, etapa="reconciliacion", codigo=codigo, corrida_id=corrida_id))


def _documento_corrida(motor: sa.Engine, *, corrida_id: str, huella: str, ruta: str) -> None:
    with sa.orm.Session(motor) as sesion, sesion.begin():
        sesion.add(
            DocumentoCorridaOrm(
                corrida_id=corrida_id,
                huella_contenido=huella,
                ruta_autorizada=ruta,
                estado="inventariado",
                version=0,
            )
        )


def test_construir_plan_devuelve_none_si_la_corrida_no_existe() -> None:
    motor = _motor()

    assert construir_plan_reintento(motor, "no-existe") is None


def test_plan_separa_reintentables_de_descartados_por_codigo() -> None:
    motor = _motor()
    repositorio = RepositorioCorridas(motor)
    repositorio.crear_corrida(Corrida.crear("corrida-1", ruta_autorizada="/datos/entrada"))
    # Reintentable: error transitorio agotado, con inventario real.
    _documento_corrida(motor, corrida_id="corrida-1", huella="a" * 64, ruta="/datos/entrada/uno.pdf")
    _cuarentena(motor, id_documento="a" * 64, codigo="error_transitorio_agotado", corrida_id="corrida-1")
    # Determinístico: parseo incompleto, se descarta.
    _documento_corrida(motor, corrida_id="corrida-1", huella="b" * 64, ruta="/datos/entrada/dos.pdf")
    _cuarentena(motor, id_documento="b" * 64, codigo="parseo_incompleto", corrida_id="corrida-1")
    # Determinístico: ambiguo, también se descarta -- mismo código que el anterior repetido dos veces.
    _documento_corrida(motor, corrida_id="corrida-1", huella="c" * 64, ruta="/datos/entrada/tres.pdf")
    _cuarentena(motor, id_documento="c" * 64, codigo="parseo_incompleto", corrida_id="corrida-1")

    plan = construir_plan_reintento(motor, "corrida-1")

    assert plan is not None
    assert plan.ruta_autorizada == "/datos/entrada"
    assert [referencia["id_documento"] for referencia in plan.reintentables] == ["a" * 64]
    assert plan.reintentables[0] == {
        "id_documento": "a" * 64,
        "uri": "/datos/entrada/uno.pdf",
        "sha256": "a" * 64,
    }
    assert plan.descartados_por_codigo == {"parseo_incompleto": 2}
    assert plan.total_descartados == 2


def test_plan_sin_apartados_no_tiene_reintentables_ni_descartados() -> None:
    motor = _motor()
    RepositorioCorridas(motor).crear_corrida(Corrida.crear("corrida-limpia"))

    plan = construir_plan_reintento(motor, "corrida-limpia")

    assert plan is not None
    assert plan.reintentables == ()
    assert plan.descartados_por_codigo == {}
    assert plan.total_descartados == 0


def test_plan_falla_ruidoso_si_falta_el_inventario_del_reintentable() -> None:
    """Centinela: un reintentable sin fila en `documento_corrida` es
    corrupción real -- nunca se reintenta con una `uri` inventada."""
    motor = _motor()
    RepositorioCorridas(motor).crear_corrida(Corrida.crear("corrida-1", ruta_autorizada="/datos"))
    _cuarentena(motor, id_documento="huerfano", codigo="error_transitorio_agotado", corrida_id="corrida-1")

    with pytest.raises(RuntimeError, match="documento_corrida"):
        construir_plan_reintento(motor, "corrida-1")
