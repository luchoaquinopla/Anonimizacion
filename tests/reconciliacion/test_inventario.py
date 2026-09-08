from dataclasses import replace
from datetime import date

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.parseo.ecg_mortara import ParseadorEcgMortara
from anonimizacion.reconciliacion.base import HallazgoCobertura, ReferenciaCampo
from anonimizacion.reconciliacion.ecg_mortara import ReconciliadorEcgMortara
from anonimizacion.reconciliacion.eco_doppler import ReconciliadorEcoDoppler
from anonimizacion.reconciliacion.inventario import verificar_cobertura


def _documento(fuentes: tuple[ReferenciaCampo, ...]) -> DocumentoParseado:
    return DocumentoParseado(
        TipoDocumento.ECG,
        1,
        IdentidadCruda(
            nombre=SecretStr("Persona Sintetica"),
            ids_internos=(SecretStr("ESTUDIO-1"),),
        ),
        date(2025, 6, 5),
        ContenidoEcg("68 BPM", "160", None, None, None),
        fuentes=fuentes,
    )


def test_hallazgo_cobertura_no_admite_identificadores_no_declarados() -> None:
    with pytest.raises(ValueError, match="campo inválido"):
        HallazgoCobertura("valor-clinico-68", 1)


def test_whitelist_ecg_ignora_solo_boilerplate_declarado() -> None:
    reconciliador = ReconciliadorEcgMortara()

    assert reconciliador.es_texto_permitido("PID / NAME MISMATCH")
    assert not reconciliador.es_texto_permitido("PR interval")


def test_whitelist_eco_permite_boilerplate_no_clinico_y_rechaza_patron_clinico() -> None:
    reconciliador = ReconciliadorEcoDoppler()

    assert reconciliador.es_texto_permitido("DIAGNOSTICO POR IMAGENES")
    assert not reconciliador.es_texto_permitido("AO | 28 | mm")
    assert reconciliador.inventariar(TextoExtraido(("DIAGNOSTICO POR IMAGENES",))) == ()
    assert [hallazgo.id_campo for hallazgo in reconciliador.inventariar(TextoExtraido(("MEDIDAS\nAO | 28 | mm",)))] == [
        "eco.medida"
    ]


def test_rechaza_claves_de_inventario_duplicadas() -> None:
    hallazgo = HallazgoCobertura("ecg.vent_rate", 1)
    with pytest.raises(ErrorParseo) as error:
        verificar_cobertura((hallazgo, hallazgo), (ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate"),))
    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_AMBIGUA


def test_rechaza_destino_sin_hallazgo_en_inventario() -> None:
    with pytest.raises(ErrorParseo) as error:
        verificar_cobertura((), (ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate"),))
    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_verificar_cobertura_devuelve_campo_no_extraido_sin_lanzar() -> None:
    """Caso benigno: un hallazgo del PDF sin destino en el modelo se
    devuelve (no se lanza) como `CAMPO_NO_EXTRAIDO` -- dirección opuesta a
    `test_rechaza_destino_sin_hallazgo_en_inventario`."""
    hallazgo = HallazgoCobertura("ecg.vent_rate", 1)

    campos_no_extraidos = verificar_cobertura((hallazgo,), ())

    assert campos_no_extraidos == ("ecg.vent_rate",)


def test_verificar_cobertura_prioriza_integridad_sobre_hallazgo_benigno() -> None:
    """Regla conservadora: si el mismo cruce tiene un hallazgo benigno para
    una clave Y un problema de integridad para otra, la integridad manda --
    el documento entero va a cuarentena y el hallazgo benigno nunca se
    devuelve."""
    hallazgo_benigno = HallazgoCobertura("ecg.vent_rate", 1)
    referencia_sin_respaldo = ReferenciaCampo("ecg.pr_interval", 1, "ecg.pr_interval")

    with pytest.raises(ErrorParseo) as error:
        verificar_cobertura((hallazgo_benigno,), (referencia_sin_respaldo,))

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_inventario_ecg_publica_con_marca_cuando_el_parseador_omite_una_medida() -> None:
    """Caso benigno (`CodigoErrorDocumento.CAMPO_NO_EXTRAIDO`): el PDF trae
    `PR interval`, el modelo sólo citó `Vent. rate`. Antes de separar
    direcciones, una medida presente en el PDF pero no citada por el
    parser mandaba el documento entero a cuarentena."""
    fuente = ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate")
    campos_no_extraidos = ReconciliadorEcgMortara().reconciliar(
        _documento((fuente,)), TextoExtraido(("Vent. rate 68 BPM\nPR interval 160",))
    )
    assert campos_no_extraidos == ("ecg.pr_interval",)


def test_inventario_ecg_rechaza_etiqueta_repetida_en_una_pagina() -> None:
    fuente = ReferenciaCampo("ecg.pr_interval", 1, "ecg.pr_interval")
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcgMortara().reconciliar(
            _documento((fuente,)), TextoExtraido(("PR interval 160\nPR interval 170",))
        )
    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_AMBIGUA
    assert error.value.campo == "ecg.pr_interval"


def test_inventario_ecg_aprueba_headers_y_medidas_con_destino_unico() -> None:
    fuentes = (
        ReferenciaCampo("ecg.nombre", 1, "ecg.nombre"),
        ReferenciaCampo("ecg.id_estudio", 1, "ecg.id_estudio"),
        ReferenciaCampo("ecg.fecha_estudio", 1, "ecg.fecha_estudio"),
        ReferenciaCampo("ecg.hora_estudio", 1, "ecg.hora_estudio"),
        ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate"),
        ReferenciaCampo("ecg.pr_interval", 1, "ecg.pr_interval"),
    )
    from datetime import time

    documento = replace(_documento(fuentes), hora_estudio=time(10, 0, 0))
    texto = TextoExtraido((
        "Persona Sintetica~, ID:ESTUDIO-1 05-JUN-2025 10:00:00\nVent. rate 68 BPM\nPR interval 160",
    ))
    ReconciliadorEcgMortara().reconciliar(documento, texto)


def test_inventario_ecg_cubre_el_modelo_generado_por_el_parseador() -> None:
    texto = TextoExtraido((
        "Persona Sintetica~, ID:ESTUDIO-1 05-JUN-2025 10:00:00\n"
        "Vent. rate 68 BPM\nPR interval 160\nQRS duration 90\n"
        "QT/QTc 380/410\nP-R-T axes 20 30 40",
    ))
    documento = ParseadorEcgMortara().parsear(texto)

    ReconciliadorEcgMortara().reconciliar(documento, texto)
