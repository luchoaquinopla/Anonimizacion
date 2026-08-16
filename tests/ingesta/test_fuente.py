"""Tests de `FuenteArtefacto`: adaptador que lista artefactos desde un filesystem local."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from anonimizacion.ingesta.artefacto import FormatoArtefacto
from anonimizacion.ingesta.fuente import FuenteArtefacto


def _crear_pdf_falso(ruta: Path, contenido: bytes) -> str:
    ruta.write_bytes(contenido)
    return hashlib.sha256(contenido).hexdigest()


def test_fuente_artefacto_lista_pdfs_de_un_directorio(tmp_path: Path) -> None:
    sha_esperado = _crear_pdf_falso(tmp_path / "doc001.pdf", b"%PDF-1.4 contenido sintetico")

    fuente = FuenteArtefacto(directorio=tmp_path)
    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    (artefacto,) = artefactos
    assert artefacto.formato is FormatoArtefacto.PDF
    assert artefacto.sha256 == sha_esperado
    assert artefacto.uri.endswith("doc001.pdf")


def test_fuente_artefacto_ignora_archivos_no_pdf(tmp_path: Path) -> None:
    (tmp_path / "notas.txt").write_text("no es un pdf")
    _crear_pdf_falso(tmp_path / "doc002.pdf", b"%PDF-1.4 otro contenido")

    fuente = FuenteArtefacto(directorio=tmp_path)
    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    assert artefactos[0].uri.endswith("doc002.pdf")


def test_fuente_artefacto_directorio_vacio_no_produce_artefactos(tmp_path: Path) -> None:
    fuente = FuenteArtefacto(directorio=tmp_path)
    assert list(fuente.listar()) == []


def test_fuente_artefacto_directorio_inexistente_falla_explicito(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FuenteArtefacto(directorio=tmp_path / "no_existe").listar()
