"""La pantalla del reporte: qué muestra, y sobre todo qué NO debe mostrar."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.salida.modelos_orm import Base, Cuarentena
from anonimizacion.web.plantilla_reporte import renderizar_reporte
from anonimizacion.web.reporte_cuarentena import construir_reporte


def _pagina(filas: list[dict[str, object]]) -> str:
    motor = sa.create_engine("sqlite://")
    Base.metadata.create_all(motor)
    with Session(motor) as sesion, sesion.begin():
        for fila in filas:
            sesion.add(Cuarentena(**fila))
    return renderizar_reporte(construir_reporte(motor))


def test_muestra_el_total_y_la_accion_de_cada_grupo() -> None:
    pagina = _pagina([
        {"id_documento": "doc-a", "etapa": "coordinacion", "codigo": "episodio_incompleto"},
        {"id_documento": "doc-b", "etapa": "parseo", "codigo": "parseo_incompleto"},
    ])

    assert "Falta material del paciente" in pagina
    assert "El programa no pudo leerlo" in pagina
    assert "Pedir al instituto" in pagina


def test_el_color_nunca_viaja_solo() -> None:
    """La paleta de estado tiene pasos por debajo de 3:1 en superficie clara a
    propósito. La mitigación es símbolo + etiqueta, y es obligatoria."""
    pagina = _pagina([
        {"id_documento": "doc-a", "etapa": "coordinacion", "codigo": "episodio_incompleto"}
    ])

    assert "#fab219" in pagina, "el grupo debe llevar su color de estado"
    assert "Falta material del paciente" in pagina, "y su etiqueta en texto"
    assert 'aria-hidden="true"' in pagina, "el símbolo es decorativo: la etiqueta es la que informa"


def test_un_grupo_vacio_no_ocupa_espacio() -> None:
    """Una ficha en cero es ruido: no aporta y compite con las que sí importan."""
    pagina = _pagina([
        {"id_documento": "doc-a", "etapa": "coordinacion", "codigo": "episodio_incompleto"}
    ])

    assert "Identidad sin resolver" not in pagina


def test_sin_casos_dice_que_no_hay_casos() -> None:
    pagina = _pagina([])

    assert "No hay estudios apartados" in pagina


def test_la_pagina_no_depende_de_la_red() -> None:
    """El pipeline es 100 % offline y esto corre en la máquina del instituto.

    Una hoja de estilos o un script externo convertirían la pantalla en
    inutilizable justo donde tiene que funcionar.
    """
    pagina = _pagina([
        {"id_documento": "doc-a", "etapa": "coordinacion", "codigo": "episodio_incompleto"}
    ])

    assert "http://" not in pagina
    assert "https://" not in pagina
    assert "<script" not in pagina


def test_el_contenido_se_escapa() -> None:
    """Los valores vienen de la base: se escapan aunque hoy no lleven PII."""
    pagina = _pagina([
        {
            "id_documento": "<img src=x onerror=alert(1)>",
            "etapa": "parseo",
            "codigo": "parseo_incompleto",
        }
    ])

    assert "<img src=x" not in pagina
    assert "&lt;img" in pagina


def test_el_sobretamano_muestra_el_tamano_y_el_tope_en_pantalla() -> None:
    pagina = _pagina([
        {
            "id_documento": "doc-grande",
            "etapa": "ingesta",
            "codigo": "artefacto_sobretamano",
            "tamano_bytes": 73_400_320,
            "tope_bytes": 52_428_800,
        }
    ])

    assert "70 MiB" in pagina
    assert "50 MiB" in pagina
