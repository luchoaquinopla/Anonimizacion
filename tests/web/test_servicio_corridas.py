"""Tests de `ServicioCorridasReal` (tasks.md 9.4/9.5/9.8/9.9): implementación real, no un doble.

Antes de esto, `ServicioCorridas` sólo existía como `Protocol` y `_ServicioFake`
en `tests/web/test_rutas_corridas.py`. La spec `portal-de-corridas` (delta)
exige que crear/consultar tenga efecto sobre datos reales -- este módulo lo
verifica con un `LanzadorCorrida` real contra SQLite en memoria, no con otro
doble.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa

from anonimizacion.dominio.errores import ErrorDocumento
from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.web.servicio_corridas import ServicioCorridasReal, construir_payload_embudo


@dataclass
class _CuarentenaFake:
    registrados: list[ErrorDocumento] = field(default_factory=list)

    def registrar(self, error: ErrorDocumento) -> None:
        self.registrados.append(error)


def _motor_con_esquema() -> sa.Engine:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def test_crear_corrida_delega_en_el_lanzador_real(tmp_path) -> None:
    """9.4: falla porque hoy `crear_corrida` es un doble que no toca ninguna base."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema()
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    servicio = ServicioCorridasReal(lanzador=lanzador, motor=motor)

    estado = servicio.crear_corrida(str(tmp_path))

    assert estado.id_corrida
    # `LanzadorCorrida.lanzar` avanza `Corrida` hasta PROCESANDO y ahora SÍ
    # persiste esa transición (`RepositorioCorridas.actualizar_corrida`,
    # hallazgo cerrado post-Fase 9): sin esto, `estado` quedaría en "creada"
    # para siempre y el campo del JSON del embudo mentiría durante toda la
    # corrida.
    assert estado.estado == "procesando"
    # Nada publicado ni apartado todavía: sólo se inventarió.
    assert estado.cuarentenas == 0


def test_consultar_corrida_refleja_el_estado_real_no_un_valor_fijo(tmp_path) -> None:
    """Requisito agregado de `portal-de-corridas`: consultar una corrida real
    refleja su estado real, no un valor fijo de prueba."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    (tmp_path / "dos.pdf").write_bytes(b"contenido-dos")
    motor = _motor_con_esquema()
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    servicio = ServicioCorridasReal(lanzador=lanzador, motor=motor)

    creada = servicio.crear_corrida(str(tmp_path))
    consultada = servicio.consultar_corrida(creada.id_corrida)

    assert consultada.id_corrida == creada.id_corrida
    assert consultada.estado == creada.estado
    # 2 documentos inventariados, 0 publicados, 0 apartados -> residuo = 2.
    assert consultada.documentos_pendientes == 2
    assert consultada.cuarentenas == 0


def test_el_json_del_embudo_informa_el_estado_real_de_una_corrida_lanzada(tmp_path) -> None:
    """El campo `estado` del contrato JSON no puede mentir `creada` para
    siempre: una corrida recién lanzada llegó a PROCESANDO, y eso tiene que
    verse en `GET /corridas/{id}/embudo` (`construir_payload_embudo`)."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema()
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)
    payload = construir_payload_embudo(motor, resultado.corrida_id)

    assert payload is not None
    assert payload["estado"] == "procesando"


def test_reintentar_corrida_lanza_notimplementederror() -> None:
    """9.8/9.9: la ruta traduce esto a 501, no a un 202 falso."""
    motor = _motor_con_esquema()
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    servicio = ServicioCorridasReal(lanzador=lanzador, motor=motor)

    with pytest.raises(NotImplementedError):
        servicio.reintentar_corrida("cualquier-id")
