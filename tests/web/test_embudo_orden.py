"""Test del orden explícito del embudo (Entrega 2, Requisito 4).

`ETAPAS_EMBUDO` debe derivarse de `ORDEN_EMBUDO` (tupla de `Etapa`, orden
verbatim de design.md D4), no ser una lista de strings independiente. Este
test fija la tupla a mano -- si alguien reordena el enum unificado, el
embudo no se mueve solo.
"""

from __future__ import annotations

from anonimizacion.pipeline.etapas import Etapa
from anonimizacion.web.embudo_corrida import ETAPAS_EMBUDO, ORDEN_EMBUDO


def test_orden_embudo_es_el_de_ejecucion_real_design_md_d4() -> None:
    assert ORDEN_EMBUDO == (
        Etapa.INGESTA,
        Etapa.DESPACHO,
        Etapa.EXTRACCION,
        Etapa.PARSEO,
        Etapa.RECONCILIACION,
        Etapa.COORDINACION,
        Etapa.PSEUDONIMIZACION,
        Etapa.SALIDA,
    )


def test_etapas_embudo_se_deriva_de_orden_embudo() -> None:
    assert ETAPAS_EMBUDO == tuple(etapa.value for etapa in ORDEN_EMBUDO)
