from __future__ import annotations

import sqlalchemy as sa

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.estados_corrida import EstadoDocumentoCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base


def _documento(corrida_id: str) -> DocumentoCorrida:
    return DocumentoCorrida.inventariado(
        corrida_id=corrida_id,
        huella_contenido="a" * 64,
        ruta_autorizada="entrada/estudio.pdf",
    )


def test_repositorio_reanuda_documento_desde_ultimo_estado_persistido() -> None:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-1")
    documento = _documento(corrida.id_corrida)
    documento.avanzar_a(EstadoDocumentoCorrida.CLASIFICADO)

    repositorio.crear_corrida(corrida)
    assert repositorio.registrar_documento(documento) is True
    assert repositorio.registrar_documento(documento) is False

    reanudado = repositorio.documentos_para_reanudar(corrida.id_corrida)

    assert len(reanudado) == 1
    assert reanudado[0].reanudar_desde() is EstadoDocumentoCorrida.CLASIFICADO


def test_repositorio_actualiza_estado_solo_con_version_esperada() -> None:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-1")
    documento = _documento(corrida.id_corrida)
    repositorio.crear_corrida(corrida)
    repositorio.registrar_documento(documento)
    documento.avanzar_a(EstadoDocumentoCorrida.CLASIFICADO)

    assert repositorio.actualizar_documento(documento, version_esperada=0) is True
    assert repositorio.actualizar_documento(documento, version_esperada=0) is False
