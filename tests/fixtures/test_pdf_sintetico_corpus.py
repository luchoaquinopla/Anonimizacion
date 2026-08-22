from __future__ import annotations

import pymupdf

from tests.fixtures.pdf_sintetico import generar_corpus_clinico


def test_corpus_con_misma_semilla_repite_oraculo_y_tres_tipos(tmp_path) -> None:
    primero = generar_corpus_clinico(tmp_path / "uno", semilla=7)
    segundo = generar_corpus_clinico(tmp_path / "dos", semilla=7)

    assert primero.oraculo == segundo.oraculo
    assert {documento.tipo for documento in primero.documentos} == {"ecg", "laboratorio", "ecocardiograma"}
    assert all(documento.ruta.read_bytes().startswith(b"%PDF") for documento in primero.documentos)


def test_corpus_usa_pii_sintetica_y_no_la_expone_en_oraculo(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=9)

    contenido = "\n".join(pymupdf.open(documento.ruta)[0].get_text() for documento in corpus.documentos)
    assert "Paciente Sintetico" in contenido
    assert "Paciente Sintetico" not in str(corpus.oraculo)
    assert all("dni" not in claves for claves in corpus.oraculo.values())
