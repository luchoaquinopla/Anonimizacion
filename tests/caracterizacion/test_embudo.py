"""Caracterización de la vista del embudo (Entrega 0, Requisito 4).

Fija el desglose EXACTO que devuelve `web/embudo_corrida.py::calcular_embudo`
para un conjunto conocido de documentos con desenlaces variados -- función
pura, sin motor ni I/O (`design.md`, D1 y D4). El fixture de entrada es
literal y reutilizable por la Entrega 2 (D4): E2 debe APROBAR este test sin
modificarlo, no romperlo.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from anonimizacion.web.embudo_corrida import calcular_embudo

pytestmark = pytest.mark.caracterizacion

#: Fixture reutilizable (ver docstring del módulo): 10 documentos entraron,
#: 6 se publicaron y 4 se apartaron en tres etapas distintas.
_ENTRARON = 10
_PUBLICADOS = 6
_PERDIDAS = {
    "ingesta": {"artefacto_sobretamano": 1},
    "parseo": {"tipo_no_reconocido": 1},
    "coordinacion": {"episodio_incompleto": 1, "episodio_ambiguo": 1},
}
_AHORA = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _embudo():
    return calcular_embudo(
        corrida_id="corrida-caracterizacion",
        entraron=_ENTRARON,
        publicados=_PUBLICADOS,
        perdidas=_PERDIDAS,
        terminados_en_ventana=0,
        primero=None,
        ultimo=None,
        ahora=_AHORA,
    )


def test_desglose_conocido_por_etapa() -> None:
    embudo = _embudo()

    assert embudo.entraron == 10
    assert embudo.publicados == 6
    assert embudo.apartados == 4
    assert embudo.residuo == 0
    assert embudo.cierra is True

    llegaron_por_etapa = {etapa.etapa: etapa.llegaron for etapa in embudo.etapas}
    apartados_por_etapa = {etapa.etapa: etapa.apartados for etapa in embudo.etapas}

    assert llegaron_por_etapa == {
        "ingesta": 10,
        "despacho": 9,
        "extraccion": 9,
        "parseo": 9,
        "reconciliacion": 8,
        "coordinacion": 8,
        "pseudonimizacion": 6,
        "salida": 6,
    }
    assert apartados_por_etapa == {
        "ingesta": 1,
        "despacho": 0,
        "extraccion": 0,
        "parseo": 1,
        "reconciliacion": 0,
        "coordinacion": 2,
        "pseudonimizacion": 0,
        "salida": 0,
    }


def test_orden_de_las_etapas_del_embudo_es_el_de_ejecucion_real() -> None:
    embudo = _embudo()
    assert tuple(etapa.etapa for etapa in embudo.etapas) == (
        "ingesta",
        "despacho",
        "extraccion",
        "parseo",
        "reconciliacion",
        "coordinacion",
        "pseudonimizacion",
        "salida",
    )
