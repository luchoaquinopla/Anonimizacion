"""Tests de la jerarquía de errores — design.md: nunca exponer el mensaje crudo."""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento, ErrorParseo


def test_error_documento_solo_transporta_metadata() -> None:
    error = ErrorDocumento(
        id_documento="doc-001",
        etapa="parseo",
        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
    )
    assert error.id_documento == "doc-001"
    assert error.etapa == "parseo"
    assert error.codigo == "parseo_incompleto"


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
    }
