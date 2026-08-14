"""Contratos RED del adaptador local de carga por lote."""

from importlib import import_module
from pathlib import Path

import pytest  # type: ignore[import-not-found]


class PuertoRegistrable:
    def __init__(self, resultados: list[object]) -> None:
        self.resultados = iter(resultados)
        self.entradas: list[bytes] = []

    def ingerir(self, contenido: bytes) -> object:
        self.entradas.append(contenido)
        resultado = next(self.resultados)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


def resultado(*, aprobada: bool, codigo: str) -> object:
    return import_module("ingesta_clinica.dominio.privacidad").SalidaTecnicaSegura(
        aprobada=aprobada,
        codigos=(codigo,),
        conteos={"documentos_aprobados" if aprobada else "documentos_rechazados": 1},
    )


def test_entrega_cada_archivo_al_puerto_y_emite_un_solo_acuse_final() -> None:
    carga = import_module("ingesta_clinica.adaptadores.entrada.carga_local")
    puerto = PuertoRegistrable(
        [
            resultado(aprobada=True, codigo="INGESTA_APROBADA"),
            resultado(aprobada=False, codigo="FAMILIA_DOCUMENTO_NO_COMPATIBLE"),
        ]
    )

    acuse = carga.AdaptadorCargaLocal(puerto).procesar_lote(
        [b"laboratorio_sintetico", b"no_laboratorio_sintetico"]
    )

    assert puerto.entradas == [b"laboratorio_sintetico", b"no_laboratorio_sintetico"]
    assert acuse.recibidos == 2
    assert acuse.procesados == 2
    assert acuse.codigos_por_archivo == (
        "INGESTA_APROBADA",
        "FAMILIA_DOCUMENTO_NO_COMPATIBLE",
    )


def test_lote_mixto_y_parcial_conserva_codigos_seguros_sin_detalles() -> None:
    carga = import_module("ingesta_clinica.adaptadores.entrada.carga_local")
    detalle_sensible = "Paciente Ana: glucosa 110; diagnostico reservado"
    puerto = PuertoRegistrable(
        [
            resultado(aprobada=True, codigo="INGESTA_APROBADA"),
            RuntimeError(detalle_sensible),
            resultado(aprobada=False, codigo="FAMILIA_DOCUMENTO_NO_COMPATIBLE"),
        ]
    )

    acuse = carga.AdaptadorCargaLocal(puerto).procesar_lote(
        [b"laboratorio", b"error", b"otra_familia"]
    )

    assert puerto.entradas == [b"laboratorio", b"error", b"otra_familia"]
    assert acuse.recibidos == acuse.procesados == 3
    assert acuse.codigos_por_archivo == (
        "INGESTA_APROBADA",
        "INGESTA_FALLIDA",
        "FAMILIA_DOCUMENTO_NO_COMPATIBLE",
    )
    assert detalle_sensible not in repr(acuse)


@pytest.mark.parametrize(
    "detalle_prohibido",
    [
        "archivo-ana.pdf",
        "texto extraido transitorio",
        "DNI 12345678",
        "hemoglobina 14.2",
        "observacion clinica",
        "diagnostico detallado",
    ],
)
def test_acuse_no_admite_datos_o_detalles_prohibidos(detalle_prohibido: str) -> None:
    carga = import_module("ingesta_clinica.adaptadores.entrada.carga_local")

    with pytest.raises(ValueError):
        carga.AcuseLoteSeguro(
            recibidos=1,
            procesados=1,
            codigos_por_archivo=(detalle_prohibido,),
        )


def test_codigo_no_permitido_del_puerto_se_reduce_a_fallo_seguro() -> None:
    carga = import_module("ingesta_clinica.adaptadores.entrada.carga_local")
    puerto = PuertoRegistrable([resultado(aprobada=False, codigo="detalle_interno")])

    acuse = carga.AdaptadorCargaLocal(puerto).procesar_lote([b"entrada_sintetica"])

    assert acuse.codigos_por_archivo == ("INGESTA_FALLIDA",)


def test_adaptador_local_no_abre_canales_de_archivo_registro_o_red() -> None:
    carga = import_module("ingesta_clinica.adaptadores.entrada.carga_local")
    interfaz = import_module("ingesta_clinica.adaptadores.entrada.interfaz_local")
    assert carga.__file__ is not None
    assert interfaz.__file__ is not None
    codigo = Path(carga.__file__).read_text(encoding="utf-8") + Path(
        interfaz.__file__
    ).read_text(encoding="utf-8")

    for dependencia_prohibida in (
        "logging",
        "tempfile",
        "pathlib",
        "socket",
        "requests",
        "urllib",
        "queue",
        "sqlite",
        "open(",
    ):
        assert dependencia_prohibida not in codigo


def test_ui_estatica_local_ofrece_arrastre_multiple_sin_exponer_resultados() -> None:
    interfaz = import_module("ingesta_clinica.adaptadores.entrada.interfaz_local")

    html = interfaz.html_interfaz_local()

    assert 'type="file"' in html
    assert "multiple" in html
    assert "drop" in html
    assert "addEventListener" in html
    assert "dataTransfer.files" in html
    assert "acuse" in html
    for texto_prohibido in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "name",
        "textContent",
        "texto extraido",
        "diagnostico",
    ):
        assert texto_prohibido not in html
