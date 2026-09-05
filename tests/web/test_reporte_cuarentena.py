"""El reporte de cuarentena agrupa por QUÉ HACER, no por código interno.

Un cardiólogo no necesita saber qué es `cobertura_ambigua`. Necesita saber si
tiene que pedirle un estudio al instituto o avisarle al equipo de desarrollo.
Esa separación es la que habilitó separar los códigos de nivel episodio de los
de nivel campo: antes compartían nombre y la pregunta no tenía respuesta.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.salida.modelos_orm import Base, Cuarentena
from anonimizacion.web.reporte_cuarentena import AccionRequerida, construir_reporte


def _motor_con(filas: list[dict[str, object]]) -> sa.Engine:
    motor = sa.create_engine("sqlite://")
    Base.metadata.create_all(motor)
    with Session(motor) as sesion, sesion.begin():
        for fila in filas:
            sesion.add(Cuarentena(**fila))
    return motor


def _fila(codigo: str, **extra: object) -> dict[str, object]:
    base = {
        "id_documento": f"doc-{codigo}",
        "etapa": "coordinacion",
        "codigo": codigo,
        "tipo_documento": "ecg",
    }
    base.update(extra)
    return base


def test_los_problemas_de_grupo_piden_material_al_instituto() -> None:
    motor = _motor_con([_fila("episodio_incompleto"), _fila("episodio_ambiguo")])

    reporte = construir_reporte(motor)

    grupo = reporte.por_accion[AccionRequerida.PEDIR_MATERIAL]
    assert grupo.total == 2


def test_los_problemas_de_lectura_van_al_equipo_de_desarrollo() -> None:
    motor = _motor_con([
        _fila("cobertura_incompleta", etapa="reconciliacion", campo="laboratorio.resultado", pagina=2),
        _fila("parseo_incompleto", etapa="parseo"),
        _fila("tipo_no_reconocido", etapa="deteccion"),
    ])

    reporte = construir_reporte(motor)

    assert reporte.por_accion[AccionRequerida.REVISAR_EL_PROGRAMA].total == 3
    assert reporte.por_accion[AccionRequerida.PEDIR_MATERIAL].total == 0


def test_la_identidad_dudosa_requiere_revision_manual() -> None:
    motor = _motor_con([_fila("clave_pii_ambigua", etapa="pseudonimizacion")])

    reporte = construir_reporte(motor)

    assert reporte.por_accion[AccionRequerida.REVISAR_A_MANO].total == 1


def test_el_reporte_distingue_episodio_de_cobertura() -> None:
    """El corazón del cambio: antes ambos eran `cobertura_*` y caían juntos."""
    motor = _motor_con([_fila("episodio_incompleto"), _fila("cobertura_incompleta")])

    reporte = construir_reporte(motor)

    assert reporte.por_accion[AccionRequerida.PEDIR_MATERIAL].total == 1
    assert reporte.por_accion[AccionRequerida.REVISAR_EL_PROGRAMA].total == 1


def test_el_sobretamano_informa_el_tamano_real_y_el_tope() -> None:
    """Cierra el circuito con la persistencia agregada: ajustar el límite es
    leer el reporte, no adivinar."""
    motor = _motor_con([
        _fila(
            "artefacto_sobretamano",
            etapa="ingesta",
            tamano_bytes=73_400_320,
            tope_bytes=52_428_800,
        )
    ])

    reporte = construir_reporte(motor)

    (detalle,) = reporte.por_accion[AccionRequerida.REVISAR_EL_PROGRAMA].detalles
    assert "70" in detalle.explicacion, "debe informar el tamaño real en MiB"
    assert "50" in detalle.explicacion, "debe informar el tope aplicado en MiB"


def test_un_codigo_desconocido_no_se_pierde_en_silencio() -> None:
    """Si aparece un código nuevo y nadie lo clasifica, tiene que verse igual.

    Descartarlo dejaría documentos apartados sin aparecer en ningún total, que
    es la clase de silencio que este proyecto viene corrigiendo.
    """
    motor = _motor_con([_fila("codigo_que_no_existe_todavia")])

    reporte = construir_reporte(motor)

    assert reporte.total == 1
    assert reporte.por_accion[AccionRequerida.SIN_CLASIFICAR].total == 1


def test_el_reporte_vacio_no_falla() -> None:
    reporte = construir_reporte(_motor_con([]))

    assert reporte.total == 0
    assert all(grupo.total == 0 for grupo in reporte.por_accion.values())
