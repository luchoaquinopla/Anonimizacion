"""Tests de `ArtefactoCrudo`: el punto de entrada del pipeline (uri+sha256+formato)."""

from __future__ import annotations

import pytest

from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto

SHA256_VALIDO = "a" * 64  # dígito hex válido, dato sintético (no un hash real)


def test_artefacto_crudo_agrupa_uri_sha256_y_formato() -> None:
    artefacto = ArtefactoCrudo(
        uri="/datos/entrada/doc001.pdf",
        sha256=SHA256_VALIDO,
        formato=FormatoArtefacto.PDF,
    )
    assert artefacto.uri == "/datos/entrada/doc001.pdf"
    assert artefacto.sha256 == SHA256_VALIDO
    assert artefacto.formato is FormatoArtefacto.PDF


def test_artefacto_crudo_es_inmutable() -> None:
    artefacto = ArtefactoCrudo(uri="x.pdf", sha256=SHA256_VALIDO, formato=FormatoArtefacto.PDF)
    with pytest.raises(Exception):
        artefacto.uri = "otro.pdf"  # type: ignore[misc]


def test_artefacto_crudo_rechaza_uri_vacia() -> None:
    with pytest.raises(ValueError):
        ArtefactoCrudo(uri="", sha256=SHA256_VALIDO, formato=FormatoArtefacto.PDF)


@pytest.mark.parametrize(
    "sha256_invalido",
    [
        "muy-corto",
        "g" * 64,  # 'g' no es hex
        "A" * 64,  # mayúsculas: sha256 hexdigest siempre es minúscula
    ],
)
def test_artefacto_crudo_rechaza_sha256_mal_formado(sha256_invalido: str) -> None:
    with pytest.raises(ValueError):
        ArtefactoCrudo(uri="x.pdf", sha256=sha256_invalido, formato=FormatoArtefacto.PDF)
