"""Tests de `FuenteArtefacto`: adaptador que lista artefactos desde un filesystem local."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from anonimizacion.ingesta.artefacto import FormatoArtefacto
from anonimizacion.ingesta.fuente import FuenteArtefacto, InventariadorDocumentos


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



def test_inventariador_rechaza_ruta_fuera_de_raices_autorizadas(tmp_path: Path) -> None:
    entrada_autorizada = tmp_path / "entrada"
    entrada_autorizada.mkdir()
    ruta_no_autorizada = tmp_path / "otra_entrada"
    ruta_no_autorizada.mkdir()

    inventariador = InventariadorDocumentos(raices_autorizadas=(entrada_autorizada,), tamano_maximo_bytes=1024)

    with pytest.raises(PermissionError):
        inventariador.inventariar(ruta_no_autorizada)


def test_inventariador_inventaria_recursivamente_y_descarta_huellas_duplicadas(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    subdirectorio = entrada / "subdirectorio"
    subdirectorio.mkdir(parents=True)
    _crear_pdf_falso(entrada / "original.pdf", b"%PDF-1.4 contenido repetido")
    _crear_pdf_falso(subdirectorio / "copia.pdf", b"%PDF-1.4 contenido repetido")
    (subdirectorio / "notas.txt").write_text("ignorar")

    inventariador = InventariadorDocumentos(raices_autorizadas=(entrada,), tamano_maximo_bytes=1024)

    artefactos = inventariador.inventariar(entrada)

    assert len(artefactos) == 1
    assert artefactos[0].uri.endswith("original.pdf")


def test_inventariador_rechaza_pdf_que_supera_tamano_maximo(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    _crear_pdf_falso(entrada / "grande.pdf", b"x" * 9)
    inventariador = InventariadorDocumentos(raices_autorizadas=(entrada,), tamano_maximo_bytes=8)

    with pytest.raises(ValueError, match="tamano"):
        inventariador.inventariar(entrada)


def test_inventariador_omite_enlace_simbolico_que_resuelve_fuera_de_la_raiz(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    externo = tmp_path / "afuera.pdf"
    _crear_pdf_falso(externo, b"%PDF-1.4 externo")
    enlace = entrada / "enlace.pdf"
    try:
        enlace.symlink_to(externo)
    except OSError as error:
        pytest.skip(f"el entorno no permite enlaces simbolicos: {error}")

    inventariador = InventariadorDocumentos(raices_autorizadas=(entrada,), tamano_maximo_bytes=1024)

    assert inventariador.inventariar(entrada) == []


def test_inventariador_detecta_destino_resuelto_fuera_de_la_raiz(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    destino_externo = tmp_path / "afuera.pdf"
    _crear_pdf_falso(destino_externo, b"%PDF-1.4 externo")

    assert InventariadorDocumentos._esta_dentro_de_raiz(destino_externo, entrada) is False
