"""Tests de `FuenteArtefacto`: adaptador que lista artefactos desde un filesystem local."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import pytest

from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.ingesta.fuente import (
    FuenteArtefacto,
    FuenteDeArtefactos,
    FuenteLocal,
    HuellasEnMemoria,
    InventariadorDocumentos,
)


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


# --- Fase 1: `Protocol FuenteDeArtefactos` -----------------------------------
#
# `FuenteLocal` todavía no implementa `abrir()` (llega en la Fase 5, PR2), así
# que el contrato se prueba acá contra dobles mínimos definidos en el propio
# test, no contra `FuenteLocal`. Es una desviación deliberada de la redacción
# literal de tasks.md 1.1 ("FuenteLocal debe satisfacer..."): probar el
# contrato contra `FuenteLocal` en esta fase daría un falso rechazo porque el
# `Protocol` exige `listar()` Y `abrir()`, y `abrir()` no existe todavía. Ver
# apply-progress.md para el detalle de la desviación.


class _FuenteDobleCompleta:
    """Doble mínimo que satisface `listar()` y `abrir()`."""

    def listar(self) -> Iterator[ArtefactoCrudo]:
        yield from ()

    def abrir(self, artefacto: ArtefactoCrudo) -> BinaryIO:  # pragma: no cover - no se invoca
        raise NotImplementedError


class _FuenteDobleIncompleta:
    """Doble que solo implementa `listar()`, sin `abrir()`."""

    def listar(self) -> Iterator[ArtefactoCrudo]:
        yield from ()


def test_protocolo_fuente_de_artefactos_acepta_adaptador_conforme() -> None:
    assert isinstance(_FuenteDobleCompleta(), FuenteDeArtefactos)


def test_protocolo_fuente_de_artefactos_rechaza_adaptador_sin_abrir() -> None:
    assert not isinstance(_FuenteDobleIncompleta(), FuenteDeArtefactos)


# --- Fase 2: trampa del generador perezoso -----------------------------------


def test_fuente_local_rechaza_ruta_fuera_de_raiz_sin_iterar(tmp_path: Path) -> None:
    entrada_autorizada = tmp_path / "entrada"
    entrada_autorizada.mkdir()
    ruta_no_autorizada = tmp_path / "otra_entrada"
    ruta_no_autorizada.mkdir()

    fuente = FuenteLocal(raices=(entrada_autorizada,), directorio=ruta_no_autorizada)

    # Sin iterar: si `listar()` fuera un generador "puro" (con `yield` en su
    # propio cuerpo), la validación no correría hasta el primer `next()` y
    # esta llamada no lanzaría nada. `listar()` MUST validar de forma ansiosa.
    with pytest.raises(PermissionError):
        fuente.listar()


def test_fuente_local_directorio_inexistente_falla_explicito_sin_iterar(tmp_path: Path) -> None:
    entrada_autorizada = tmp_path / "entrada"
    entrada_autorizada.mkdir()

    fuente = FuenteLocal(raices=(entrada_autorizada,), directorio=entrada_autorizada / "no_existe")

    with pytest.raises(FileNotFoundError):
        fuente.listar()


def test_fuente_local_lista_pdfs_de_directorio_autorizado(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    sha_esperado = _crear_pdf_falso(entrada / "doc001.pdf", b"%PDF-1.4 contenido sintetico")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    (artefacto,) = artefactos
    assert artefacto.formato is FormatoArtefacto.PDF
    assert artefacto.sha256 == sha_esperado


# --- Fase 3: deduplicación delegada ------------------------------------------


def test_huellas_en_memoria_marca_segunda_huella_repetida_como_no_nueva() -> None:
    huellas = HuellasEnMemoria()
    sha = "a" * 64

    assert huellas.es_nueva(sha) is True
    assert huellas.es_nueva(sha) is False


def test_fuente_local_omite_contenido_duplicado_via_registro_de_huellas(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    _crear_pdf_falso(entrada / "original.pdf", b"%PDF-1.4 contenido repetido")
    _crear_pdf_falso(entrada / "copia.pdf", b"%PDF-1.4 contenido repetido")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada, huellas=HuellasEnMemoria())
    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
