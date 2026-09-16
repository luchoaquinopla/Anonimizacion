"""Test de deriva del vocabulario de etapas (Entrega 2, Requisito 3).

Recorre `src/` con `ast` (sin importar módulos) y junta todo `_ETAPA = "..."`
declarado a nivel de módulo. Si alguien agrega una etapa de un solo lado
(un parser nuevo, o un miembro nuevo en `EtapaDocumento`/`Etapa`), este test
falla -- es el mecanismo que hubiera atrapado `pipeline/ejecutor.py:508`
(`Etapa.COORDINACION.value` sin que `EtapaDocumento` tuviera ese miembro).
"""

from __future__ import annotations

import ast
from pathlib import Path

from anonimizacion.dominio.errores import EtapaDocumento
from anonimizacion.pipeline.etapas import Etapa

_SRC = Path(__file__).resolve().parents[2] / "src" / "anonimizacion"


def _valores_etapa_declarados_en_src() -> dict[str, Path]:
    """Mapa `valor -> archivo` de todo `_ETAPA = "..."` a nivel de módulo."""
    valores: dict[str, Path] = {}
    for archivo in _SRC.rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        for nodo in ast.iter_child_nodes(arbol):
            if not isinstance(nodo, ast.Assign):
                continue
            if not any(isinstance(objetivo, ast.Name) and objetivo.id == "_ETAPA" for objetivo in nodo.targets):
                continue
            if isinstance(nodo.value, ast.Constant) and isinstance(nodo.value.value, str):
                valores[nodo.value.value] = archivo
    return valores


def test_todo_etapa_declarado_en_src_es_miembro_del_enum_unificado() -> None:
    valores_unificados = {etapa.value for etapa in Etapa}
    declarados = _valores_etapa_declarados_en_src()

    sin_correspondencia = {valor: archivo for valor, archivo in declarados.items() if valor not in valores_unificados}

    assert not sin_correspondencia, (
        f"_ETAPA sin correspondencia en Etapa: {sin_correspondencia}"
    )


def test_etapa_documento_es_subconjunto_del_enum_unificado() -> None:
    valores_documento = {etapa.value for etapa in EtapaDocumento}
    valores_unificados = {etapa.value for etapa in Etapa}

    assert valores_documento <= valores_unificados
