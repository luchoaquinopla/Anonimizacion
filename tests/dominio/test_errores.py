"""Tests de la jerarquía de errores — design.md: nunca exponer el mensaje crudo."""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import (
    CodigoErrorDocumento,
    ErrorDocumento,
    ErrorParseo,
    EtapaDocumento,
)


def test_error_documento_solo_transporta_metadata() -> None:
    error = ErrorDocumento(
        id_documento="doc-001",
        etapa="parseo",
        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
    )
    assert error.id_documento == "doc-001"
    assert error.etapa == "parseo"
    assert error.codigo == "parseo_incompleto"


def test_error_documento_transporta_tipo_documento_seguro() -> None:
    from anonimizacion.dominio.tipos_documento import TipoDocumento

    error = ErrorDocumento("doc-001", "parseo", CodigoErrorDocumento.PARSEO_INCOMPLETO, tipo_documento=TipoDocumento.LABORATORIO)

    assert error.tipo_documento is TipoDocumento.LABORATORIO


def test_error_documento_rechaza_tipo_documento_fuera_del_catalogo() -> None:
    with pytest.raises(ValueError):
        ErrorDocumento("doc-001", "parseo", CodigoErrorDocumento.PARSEO_INCOMPLETO, tipo_documento="valor-no-seguro")  # type: ignore[arg-type]


def test_error_documento_es_inmutable() -> None:
    error = ErrorDocumento(
        id_documento="doc-001", etapa="parseo", codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO
    )
    with pytest.raises(AttributeError):
        error.codigo = CodigoErrorDocumento.TIPO_NO_RECONOCIDO  # type: ignore[misc]


def test_error_parseo_expone_codigo_no_mensaje_crudo() -> None:
    excepcion = ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa="parseo")
    assert excepcion.codigo == "parseo_incompleto"
    assert excepcion.etapa == "parseo"
    assert str(excepcion) == "parseo_incompleto"


def test_error_parseo_permite_etapa_distinta_de_parseo() -> None:
    excepcion = ErrorParseo(codigo=CodigoErrorDocumento.TIPO_NO_RECONOCIDO, etapa="deteccion")
    assert excepcion.etapa == "deteccion"


def test_codigos_de_error_deterministico_no_se_reintentan() -> None:
    codigos = {miembro.value for miembro in CodigoErrorDocumento}
    assert codigos == {
        "tipo_no_reconocido",
        "parseo_incompleto",
        "clave_pii_no_resuelta",
        "clave_pii_ambigua",
        "error_transitorio_agotado",
        "evidencia_ausente",
        "evidencia_ambigua",
        "valor_discrepante",
        "cobertura_incompleta",
        "episodio_incompleto",
        "episodio_ambiguo",
        "cobertura_ambigua",
        "artefacto_sobretamano",
    }


def test_reconciliacion_tiene_etapa_y_codigos_seguros() -> None:
    error = ErrorParseo(
        codigo=CodigoErrorDocumento.VALOR_DISCREPANTE,
        etapa=EtapaDocumento.RECONCILIACION,
    )
    assert error.etapa == EtapaDocumento.RECONCILIACION
    assert str(error) == "valor_discrepante"


def test_error_documento_admite_solo_metadata_de_reconciliacion() -> None:
    error = ErrorDocumento(
        id_documento="doc-001",
        etapa=EtapaDocumento.RECONCILIACION,
        codigo=CodigoErrorDocumento.EVIDENCIA_AUSENTE,
        campo="ecg.vent_rate",
        pagina=1,
    )
    assert error.campo == "ecg.vent_rate"
    assert error.pagina == 1
    assert {"valor", "texto", "huella", "dni"}.isdisjoint(vars(error))


def test_error_documento_rechaza_campo_fuera_de_whitelist() -> None:
    with pytest.raises(ValueError):
        ErrorDocumento(
            id_documento="doc-001",
            etapa=EtapaDocumento.RECONCILIACION,
            codigo=CodigoErrorDocumento.EVIDENCIA_AUSENTE,
            campo="ecg.valor-4a75616e",
        )


def test_error_parseo_transporta_solo_campo_y_pagina_seguros() -> None:
    error = ErrorParseo(
        codigo=CodigoErrorDocumento.EVIDENCIA_AUSENTE,
        etapa=EtapaDocumento.RECONCILIACION,
        campo="ecg.vent_rate",
        pagina=1,
    )
    assert error.campo == "ecg.vent_rate"
    assert error.pagina == 1
