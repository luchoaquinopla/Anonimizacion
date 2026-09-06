from __future__ import annotations

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.estados_corrida import EstadoCorrida, EstadoDocumentoCorrida


def test_corrida_avanza_por_estados_esperados() -> None:
    corrida = Corrida.crear("corrida-1")

    corrida.avanzar_a(EstadoCorrida.INVENTARIANDO)
    corrida.avanzar_a(EstadoCorrida.PROCESANDO)
    corrida.avanzar_a(EstadoCorrida.RECONCILIANDO)
    corrida.avanzar_a(EstadoCorrida.PUBLICANDO)
    corrida.avanzar_a(EstadoCorrida.COMPLETADA)

    assert corrida.estado is EstadoCorrida.COMPLETADA
    assert corrida.version == 5


def test_documento_reanuda_desde_ultimo_estado_confirmado() -> None:
    corrida = Corrida.crear("corrida-1")
    documento = DocumentoCorrida.inventariado(
        corrida_id=corrida.id_corrida,
        huella_contenido="a" * 64,
        ruta_autorizada="entrada/estudio.pdf",
    )
    documento.avanzar_a(EstadoDocumentoCorrida.CLASIFICADO)
    documento.avanzar_a(EstadoDocumentoCorrida.EXTRAIDO_MINIMO)

    assert documento.reanudar_desde() is EstadoDocumentoCorrida.EXTRAIDO_MINIMO
