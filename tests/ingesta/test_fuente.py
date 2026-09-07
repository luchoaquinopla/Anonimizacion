"""Tests de `FuenteLocal`: adaptador unificado de ingesta local (filesystem)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento, EtapaDocumento
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.ingesta.fuente import (
    FuenteDeArtefactos,
    FuenteLocal,
    HuellasEnMemoria,
)


def _crear_pdf_falso(ruta: Path, contenido: bytes) -> str:
    ruta.write_bytes(contenido)
    return hashlib.sha256(contenido).hexdigest()


class _CuarentenaFalsa:
    """Doble de `SumideroCuarentena`: acumula errores en memoria para asertar."""

    def __init__(self) -> None:
        self.errores: list[ErrorDocumento] = []

    def registrar(self, error: ErrorDocumento) -> None:
        self.errores.append(error)


# --- Fase 1: `Protocol FuenteDeArtefactos` -----------------------------------
#
# Deuda de PR1 saldada: `FuenteLocal.abrir()` ya existe (Fase 5), así que el
# contrato se verifica también contra la implementación real, no solo contra
# dobles mínimos. Se conservan los dobles porque siguen probando el rechazo
# estructural de un adaptador incompleto, algo que la implementación real no
# puede ejercitar por construcción.


class _FuenteDobleCompleta:
    """Doble mínimo que satisface `listar()`, `listar_grupos()` y `abrir()`."""

    def listar(self) -> Iterator[ArtefactoCrudo]:
        yield from ()

    def listar_grupos(self) -> Iterator[tuple[ArtefactoCrudo, ...]]:
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


def test_protocolo_fuente_de_artefactos_acepta_fuente_local_real(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)

    assert isinstance(fuente, FuenteDeArtefactos)


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


def test_fuente_local_directorio_vacio_no_produce_artefactos(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)

    assert list(fuente.listar()) == []


def test_fuente_local_ignora_archivos_no_pdf(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    (entrada / "notas.txt").write_text("no es un pdf")
    _crear_pdf_falso(entrada / "doc002.pdf", b"%PDF-1.4 otro contenido")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    assert artefactos[0].uri.endswith("doc002.pdf")


def test_fuente_local_aparta_extension_no_soportada_en_vez_de_descartarla(tmp_path: Path) -> None:
    """Un `.jpg`/`.doc`/`.pdf.tmp` no debe evaporarse sin dejar rastro: tiene que
    aparecer en cuarentena con un motivo propio, igual que el sobretamaño."""
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    (entrada / "radiografia.jpg").write_bytes(b"contenido-no-pdf")
    sha_valido = _crear_pdf_falso(entrada / "doc.pdf", b"%PDF-1.4 valido")

    cuarentena = _CuarentenaFalsa()
    fuente = FuenteLocal(raices=(entrada,), directorio=entrada, cuarentena=cuarentena)

    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    assert artefactos[0].sha256 == sha_valido
    assert len(cuarentena.errores) == 1
    (error,) = cuarentena.errores
    assert error.codigo is CodigoErrorDocumento.FORMATO_NO_SOPORTADO
    assert error.etapa is EtapaDocumento.INGESTA


def test_fuente_local_no_aparta_directorios_con_extension_no_soportada(tmp_path: Path) -> None:
    """Un directorio (incluso con nombre `algo.jpg`) no es un hallazgo de
    ingesta: no se lee, no se aparta -- se sigue omitiendo en silencio."""
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    (entrada / "subcarpeta.jpg").mkdir()
    sha_valido = _crear_pdf_falso(entrada / "doc.pdf", b"%PDF-1.4 valido")

    cuarentena = _CuarentenaFalsa()
    fuente = FuenteLocal(raices=(entrada,), directorio=entrada, cuarentena=cuarentena)

    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    assert artefactos[0].sha256 == sha_valido
    assert cuarentena.errores == []


def test_fuente_local_no_aparta_archivo_oculto_con_extension_no_soportada(tmp_path: Path) -> None:
    """Un archivo oculto no soportado no es un hallazgo del corpus: se sigue
    omitiendo en silencio, como hoy -- no se aparta a cuarentena."""
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    (entrada / ".oculto.jpg").write_bytes(b"contenido-oculto")
    sha_valido = _crear_pdf_falso(entrada / "doc.pdf", b"%PDF-1.4 valido")

    cuarentena = _CuarentenaFalsa()
    fuente = FuenteLocal(raices=(entrada,), directorio=entrada, cuarentena=cuarentena)

    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    assert artefactos[0].sha256 == sha_valido
    assert cuarentena.errores == []


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


# --- Fase 4: `FuenteLocal` -- pereza, hasheo, tope, cuarentena ---------------


def test_fuente_local_es_perezosa_no_hashea_mas_de_lo_necesario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    for nombre in ("a.pdf", "b.pdf", "c.pdf"):
        _crear_pdf_falso(entrada / nombre, f"contenido-{nombre}".encode())

    original = FuenteLocal._calcular_huella
    llamados: list[Path] = []

    def _huella_contada(ruta: Path) -> str:
        llamados.append(ruta)
        return original(ruta)

    monkeypatch.setattr(FuenteLocal, "_calcular_huella", staticmethod(_huella_contada))

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    iterador = fuente.listar()
    next(iterador)

    assert len(llamados) == 1


def test_fuente_local_hasheo_por_bloques_coincide_con_hash_completo(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    # Mayor a un bloque (1 MiB) para forzar más de una iteración de lectura.
    contenido = b"%PDF-1.4" + b"x" * (3 * 1024 * 1024)
    ruta = entrada / "grande.pdf"
    ruta.write_bytes(contenido)
    esperado = hashlib.sha256(contenido).hexdigest()

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    (artefacto,) = list(fuente.listar())

    assert artefacto.sha256 == esperado


def test_fuente_local_omite_enlace_simbolico_que_resuelve_fuera_de_la_raiz(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    externo = tmp_path / "afuera.pdf"
    _crear_pdf_falso(externo, b"%PDF-1.4 externo")
    enlace = entrada / "enlace.pdf"
    try:
        enlace.symlink_to(externo)
    except OSError as error:
        pytest.skip(f"el entorno no permite enlaces simbolicos: {error}")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)

    assert list(fuente.listar()) == []


def test_fuente_local_rechaza_ruta_fuera_de_raices_autorizadas(tmp_path: Path) -> None:
    entrada_autorizada = tmp_path / "entrada"
    entrada_autorizada.mkdir()
    ruta_no_autorizada = tmp_path / "otra_entrada"
    ruta_no_autorizada.mkdir()

    fuente = FuenteLocal(raices=(entrada_autorizada,), directorio=ruta_no_autorizada)

    with pytest.raises(PermissionError):
        fuente.listar()


def test_fuente_local_tope_por_defecto_es_50_mebibytes(tmp_path: Path) -> None:
    fuente = FuenteLocal(raices=(tmp_path,), directorio=tmp_path)

    assert fuente.tope_bytes == 50 * 1024 * 1024


def test_fuente_local_archivo_sobretamano_va_a_cuarentena_y_continua_el_lote(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    _crear_pdf_falso(entrada / "grande.pdf", b"x" * 20)
    sha_valido = _crear_pdf_falso(entrada / "valido.pdf", b"x" * 5)

    cuarentena = _CuarentenaFalsa()
    fuente = FuenteLocal(raices=(entrada,), directorio=entrada, tope_bytes=10, cuarentena=cuarentena)

    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    assert artefactos[0].sha256 == sha_valido
    assert len(cuarentena.errores) == 1
    (error,) = cuarentena.errores
    assert error.codigo is CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO
    assert error.etapa is EtapaDocumento.INGESTA
    assert error.tamano_bytes == 20
    assert error.tope_bytes == 10


def test_fuente_local_tope_de_tamano_es_frontera_exacta(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    _crear_pdf_falso(entrada / "limite.pdf", b"x" * 10)
    _crear_pdf_falso(entrada / "excede.pdf", b"x" * 11)

    cuarentena = _CuarentenaFalsa()
    fuente = FuenteLocal(raices=(entrada,), directorio=entrada, tope_bytes=10, cuarentena=cuarentena)

    artefactos = list(fuente.listar())

    assert len(artefactos) == 1
    assert artefactos[0].uri.endswith("limite.pdf")
    assert len(cuarentena.errores) == 1


# --- Fase 5: `abrir()` -- revalidación y verificación ------------------------


def test_fuente_local_abrir_retorna_flujo_legible_con_contenido_real(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    contenido = b"%PDF-1.4 contenido real"
    _crear_pdf_falso(entrada / "doc.pdf", contenido)

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    (artefacto,) = list(fuente.listar())

    with fuente.abrir(artefacto) as flujo:
        assert flujo.read() == contenido


def test_fuente_local_abrir_rechaza_uri_fuera_de_raices_autorizadas(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    externo = tmp_path / "afuera.pdf"
    sha = _crear_pdf_falso(externo, b"%PDF-1.4 externo")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    # Simula una cola envenenada: un `ArtefactoCrudo` con `uri` fuera de las
    # raíces autorizadas del adaptador, como si viniera de un mensaje manipulado.
    artefacto_envenenado = ArtefactoCrudo(uri=str(externo), sha256=sha, formato=FormatoArtefacto.PDF)

    with pytest.raises(PermissionError):
        fuente.abrir(artefacto_envenenado)


def test_fuente_local_abrir_rechaza_sha256_que_no_coincide_con_contenido_real(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    ruta = entrada / "doc.pdf"
    _crear_pdf_falso(ruta, b"%PDF-1.4 contenido real")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    artefacto_falsificado = ArtefactoCrudo(uri=str(ruta), sha256="a" * 64, formato=FormatoArtefacto.PDF)

    with pytest.raises(ValueError, match="sha256"):
        fuente.abrir(artefacto_falsificado)


# --- Fase 6: `listar_grupos()` -- agrupamiento real (paralelismo-de-procesamiento PR 2) --


def test_fuente_local_listar_grupos_un_grupo_por_subdirectorio_inmediato(tmp_path: Path) -> None:
    """Criterio del instituto (reunión 2026-08-21): una carpeta por paciente."""
    entrada = tmp_path / "entrada"
    (entrada / "paciente-a").mkdir(parents=True)
    (entrada / "paciente-b").mkdir(parents=True)
    _crear_pdf_falso(entrada / "paciente-a" / "lab.pdf", b"contenido-a-lab")
    _crear_pdf_falso(entrada / "paciente-a" / "ecg.pdf", b"contenido-a-ecg")
    _crear_pdf_falso(entrada / "paciente-b" / "eco.pdf", b"contenido-b-eco")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    grupos = list(fuente.listar_grupos())

    assert len(grupos) == 2
    tamanos = sorted(len(grupo) for grupo in grupos)
    assert tamanos == [1, 2]


def test_fuente_local_listar_grupos_corpus_plano_es_un_solo_grupo(tmp_path: Path) -> None:
    """Advertencia del proposal: si el corpus llega sin subcarpetas, el
    agrupamiento real degrada a un solo grupo -- el paralelismo del tramo 3
    rendiría cero, pero la partición sigue siendo correcta."""
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    _crear_pdf_falso(entrada / "uno.pdf", b"contenido-uno")
    _crear_pdf_falso(entrada / "dos.pdf", b"contenido-dos")
    _crear_pdf_falso(entrada / "tres.pdf", b"contenido-tres")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    grupos = list(fuente.listar_grupos())

    assert len(grupos) == 1
    assert len(grupos[0]) == 3


def test_fuente_local_listar_grupos_corpus_plano_grande_no_se_trocea(tmp_path: Path) -> None:
    """Centinela de correctitud (revisión adversarial, hallazgo crítico 2):
    una versión anterior de esta función troceaba un corpus plano grande en
    sub-grupos sintéticos de tamaño fijo para acotar RAM -- eso partía
    pacientes entre dos cortes por orden alfabético de ruta, sin ningún
    criterio clínico, y cada paciente partido terminaba en
    `EPISODIO_INCOMPLETO` en ambos cortes. Se revirtió: un corpus plano,
    sin importar cuántos archivos tenga, es SIEMPRE un solo grupo -- la
    memoria no está acotada en ese caso degenerado, a propósito (ver
    docstring del módulo). Si esto vuelve a fallar, alguien reintrodujo el
    troceo sin agregar de nuevo esta protección."""
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    total_archivos = 1005  # mayor al viejo _TOPE_SUBGRUPO_RAIZ (1000), a propósito
    for indice in range(total_archivos):
        _crear_pdf_falso(entrada / f"doc-{indice:05d}.pdf", f"contenido-{indice}".encode())

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    grupos = list(fuente.listar_grupos())

    assert len(grupos) == 1
    assert len(grupos[0]) == total_archivos


def test_fuente_local_listar_grupos_particion_es_disjunta_y_exhaustiva(tmp_path: Path) -> None:
    """La invariante del embudo (`residuo = entraron - con_desenlace`) exige que
    ningún documento se cuente dos veces ni se pierda: la unión de los grupos
    debe ser exactamente igual al conjunto que devuelve `listar()`."""
    entrada = tmp_path / "entrada"
    (entrada / "paciente-a").mkdir(parents=True)
    (entrada / "paciente-b").mkdir(parents=True)
    _crear_pdf_falso(entrada / "suelto.pdf", b"contenido-suelto")
    _crear_pdf_falso(entrada / "paciente-a" / "lab.pdf", b"contenido-a-lab")
    _crear_pdf_falso(entrada / "paciente-b" / "eco.pdf", b"contenido-b-eco")

    fuente_plana = FuenteLocal(raices=(entrada,), directorio=entrada)
    shas_planos = {artefacto.sha256 for artefacto in fuente_plana.listar()}

    fuente_agrupada = FuenteLocal(raices=(entrada,), directorio=entrada)
    grupos = list(fuente_agrupada.listar_grupos())
    shas_agrupados = [artefacto.sha256 for grupo in grupos for artefacto in grupo]

    # Exhaustiva: la unión de los grupos cubre todo lo que ve `listar()`.
    assert set(shas_agrupados) == shas_planos
    # Disjunta: nada se cuenta dos veces entre grupos.
    assert len(shas_agrupados) == len(set(shas_agrupados))


def test_fuente_local_listar_grupos_hereda_tope_de_tamano_y_cuarentena(tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    (entrada / "paciente-a").mkdir(parents=True)
    _crear_pdf_falso(entrada / "paciente-a" / "grande.pdf", b"x" * 20)
    sha_valido = _crear_pdf_falso(entrada / "paciente-a" / "chico.pdf", b"x" * 5)

    cuarentena = _CuarentenaFalsa()
    fuente = FuenteLocal(raices=(entrada,), directorio=entrada, tope_bytes=10, cuarentena=cuarentena)

    (grupo,) = list(fuente.listar_grupos())

    assert len(grupo) == 1
    assert grupo[0].sha256 == sha_valido
    assert len(cuarentena.errores) == 1


def test_fuente_local_listar_grupos_hereda_dedup_por_contenido(tmp_path: Path) -> None:
    """Gotcha documentado (design.md): la dedup es global a la enumeración --
    un PDF idéntico repetido en dos carpetas se descarta en la segunda."""
    entrada = tmp_path / "entrada"
    (entrada / "paciente-a").mkdir(parents=True)
    (entrada / "paciente-b").mkdir(parents=True)
    _crear_pdf_falso(entrada / "paciente-a" / "original.pdf", b"contenido-repetido")
    _crear_pdf_falso(entrada / "paciente-b" / "copia.pdf", b"contenido-repetido")

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    grupos = list(fuente.listar_grupos())

    total = sum(len(grupo) for grupo in grupos)
    assert total == 1


def test_fuente_local_listar_grupos_valida_ansiosamente_sin_iterar(tmp_path: Path) -> None:
    entrada_autorizada = tmp_path / "entrada"
    entrada_autorizada.mkdir()
    ruta_no_autorizada = tmp_path / "otra_entrada"
    ruta_no_autorizada.mkdir()

    fuente = FuenteLocal(raices=(entrada_autorizada,), directorio=ruta_no_autorizada)

    with pytest.raises(PermissionError):
        fuente.listar_grupos()


def test_fuente_local_listar_grupos_es_perezoso_no_hashea_mas_de_lo_necesario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No debe materializar la partición completa antes de entregar el primer
    grupo -- perezoso, no ansioso (ver docstring del módulo y el gotcha de
    `puerto-de-ingesta` sobre generadores perezosos).

    `itertools.groupby` necesita mirar UN elemento del grupo siguiente para
    saber que el grupo actual terminó (es inherente a cómo detecta el borde
    de un grupo) -- por eso el tercer paciente ("paciente-c") nunca se toca,
    pero un archivo de "paciente-b" sí, como lookahead mínimo."""
    entrada = tmp_path / "entrada"
    for nombre_paciente in ("paciente-a", "paciente-b", "paciente-c"):
        carpeta = entrada / nombre_paciente
        carpeta.mkdir(parents=True)
        for indice in range(2):
            _crear_pdf_falso(carpeta / f"doc{indice}.pdf", f"contenido-{nombre_paciente}-{indice}".encode())

    original = FuenteLocal._calcular_huella
    llamados: list[Path] = []

    def _huella_contada(ruta: Path) -> str:
        llamados.append(ruta)
        return original(ruta)

    monkeypatch.setattr(FuenteLocal, "_calcular_huella", staticmethod(_huella_contada))

    fuente = FuenteLocal(raices=(entrada,), directorio=entrada)
    iterador = fuente.listar_grupos()
    next(iterador)

    assert not any("paciente-c" in str(ruta) for ruta in llamados)
    assert len(llamados) < 6  # 3 pacientes x 2 docs: no se hashea el corpus entero
