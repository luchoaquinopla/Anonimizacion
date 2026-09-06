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
    assert repositorio.registrar_documentos([documento]) == 1
    assert repositorio.registrar_documentos([documento]) == 0

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
    repositorio.registrar_documentos([documento])
    documento.avanzar_a(EstadoDocumentoCorrida.CLASIFICADO)

    assert repositorio.actualizar_documento(documento, version_esperada=0) is True
    assert repositorio.actualizar_documento(documento, version_esperada=0) is False


def test_repositorio_actualiza_estado_de_corrida_solo_con_version_esperada() -> None:
    """Mismo patrón de bloqueo optimista que `actualizar_documento`, para `Corrida`.

    Sin esto, `CorridaOrm.estado` queda en `creada` para siempre: las
    transiciones que `Corrida.avanzar_a` hace en memoria (`LanzadorCorrida`)
    nunca se persisten -- y el campo `estado` del JSON del embudo termina
    mintiendo durante toda la corrida.
    """
    from anonimizacion.dominio.estados_corrida import EstadoCorrida
    from anonimizacion.salida.modelos_orm import CorridaOrm

    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-1")
    repositorio.crear_corrida(corrida)

    corrida.avanzar_a(EstadoCorrida.INVENTARIANDO)

    assert repositorio.actualizar_corrida(corrida, version_esperada=0) is True
    assert repositorio.actualizar_corrida(corrida, version_esperada=0) is False

    with sa.orm.Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, "corrida-1")
    assert fila.estado == EstadoCorrida.INVENTARIANDO.value
    assert fila.version == 1


# --- registrar_documentos por lote (Decisión 5, design.md) -------------------
#
# Motivo medido: abrir una `Session` y una transacción POR DOCUMENTO -- 100.000
# transacciones sueltas son minutos de arranque para un trabajo que en una
# sesión por millar son segundos. Esta es la versión por lote, con la misma
# guarda de idempotencia por `(corrida_id, huella_contenido)`.


def _documentos(corrida_id: str, cantidad: int) -> list[DocumentoCorrida]:
    return [
        DocumentoCorrida.inventariado(
            corrida_id=corrida_id,
            huella_contenido=f"{indice:0>64}",
            ruta_autorizada=f"entrada/doc-{indice}.pdf",
        )
        for indice in range(cantidad)
    ]


def test_registrar_documentos_inventaria_todos_los_documentos_del_lote() -> None:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-lote")
    repositorio.crear_corrida(corrida)

    assert repositorio.registrar_documentos(_documentos("corrida-lote", 3), tamano_lote=1000) == 3


def test_registrar_documentos_particiona_en_varios_lotes() -> None:
    """Con `tamano_lote` menor a la cantidad total, igual se inventarian todos
    -- una sesión por lote, no una sesión para todo el inventario."""
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-lote")
    repositorio.crear_corrida(corrida)

    total = repositorio.registrar_documentos(_documentos("corrida-lote", 7), tamano_lote=3)

    assert total == 7
    documentos = repositorio.documentos_para_reanudar("corrida-lote")
    assert len(documentos) == 7


def test_registrar_documentos_dos_veces_no_duplica_el_denominador() -> None:
    """6.3: `uq_documento_corrida_huella` evita duplicar el denominador del
    embudo si el mismo inventario se registra dos veces (relanzar la misma
    corrida)."""
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-lote")
    repositorio.crear_corrida(corrida)
    lote = _documentos("corrida-lote", 5)

    primero = repositorio.registrar_documentos(lote, tamano_lote=1000)
    segundo = repositorio.registrar_documentos(lote, tamano_lote=1000)

    assert primero == 5
    assert segundo == 0, "el mismo inventario registrado dos veces no debe duplicar filas"
    assert len(repositorio.documentos_para_reanudar("corrida-lote")) == 5
