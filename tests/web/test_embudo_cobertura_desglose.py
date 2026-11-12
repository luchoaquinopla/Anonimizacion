"""Cobertura del desglose del embudo (Entrega 2, Requisito 4).

Todo miembro de `EtapaDocumento` debe estar en `ORDEN_EMBUDO` **o** en la
lista explícita de exclusión con motivo escrito. Sin este test, una etapa
nueva puede caerse del desglose en silencio -- exactamente el defecto que
sufrió `despacho` antes de agregarse (ver comentario en `embudo_corrida.py`).
"""

from __future__ import annotations

from anonimizacion.dominio.errores import EtapaDocumento
from anonimizacion.web.embudo_corrida import ETAPAS_EXCLUIDAS_DEL_EMBUDO, ORDEN_EMBUDO


def test_todo_etapa_documento_esta_en_el_embudo_o_en_la_exclusion_explicita() -> None:
    valores_incluidos = {etapa.value for etapa in ORDEN_EMBUDO}
    valores_excluidos = {etapa.value for etapa in ETAPAS_EXCLUIDAS_DEL_EMBUDO}

    sin_cobertura = {
        etapa.value for etapa in EtapaDocumento if etapa.value not in valores_incluidos and etapa.value not in valores_excluidos
    }

    assert not sin_cobertura, f"Etapas de EtapaDocumento sin cobertura en el embudo: {sin_cobertura}"
