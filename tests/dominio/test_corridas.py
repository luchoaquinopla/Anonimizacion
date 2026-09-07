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


def test_corrida_procesando_cierra_directo_sin_pasos_de_reconciliacion_fantasma() -> None:
    """Feature `despachador-desde-el-panel`: en esta arquitectura,
    `trabajadores.tareas.procesar_grupo` ya reconcilia y publica CADA grupo
    de punta a punta, en una sola llamada síncrona (Fase 2.5,
    `operacion-segura-y-escalable`) -- no hay ningún paso administrativo
    separado de "reconciliando" ni "publicando" que el despachador real
    atraviese. Forzar la corrida a pasar por esos estados para cerrarla
    inventaría una fase que nadie ejecuta -- la misma clase de mentira que
    `fix/silencios-de-ingesta-y-panel` ya cerró en la punta de arranque
    (`PROCESANDO` sin que nada procese). PROCESANDO cierra DIRECTO a un
    estado terminal, para ambos desenlaces reales del despacho."""
    exitosa = Corrida.crear("corrida-exito")
    exitosa.avanzar_a(EstadoCorrida.INVENTARIANDO)
    exitosa.avanzar_a(EstadoCorrida.PROCESANDO)
    exitosa.avanzar_a(EstadoCorrida.COMPLETADA)
    assert exitosa.estado is EstadoCorrida.COMPLETADA

    con_cuarentena = Corrida.crear("corrida-cuarentena")
    con_cuarentena.avanzar_a(EstadoCorrida.INVENTARIANDO)
    con_cuarentena.avanzar_a(EstadoCorrida.PROCESANDO)
    con_cuarentena.avanzar_a(EstadoCorrida.COMPLETADA_CON_CUARENTENA)
    assert con_cuarentena.estado is EstadoCorrida.COMPLETADA_CON_CUARENTENA


def test_corrida_creada_puede_marcarse_fallida_por_recuperacion_de_arranque() -> None:
    """Feature `despachador-desde-el-panel`: el servidor es de UN SOLO
    proceso, sin persistencia de "hay un hilo corriendo para este
    corrida_id" -- si el proceso muere entre `crear_corrida` (fila insertada
    en CREADA) y el primer `avanzar_a(INVENTARIANDO)`, esa fila queda
    abandonada en CREADA. La recuperación de arranque (`recuperar_corridas_abandonadas`)
    necesita poder cerrarla igual que cualquier otro estado no terminal."""
    corrida = Corrida.crear("corrida-abandonada-en-creada")
    corrida.avanzar_a(EstadoCorrida.FALLIDA)
    assert corrida.estado is EstadoCorrida.FALLIDA


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
