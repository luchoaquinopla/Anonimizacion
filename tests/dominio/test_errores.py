"""Tests de la jerarquía de errores — design.md: nunca exponer el mensaje crudo."""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import (
    CodigoErrorDocumento,
    DetalleParseoIncompleto,
    ErrorDocumento,
    ErrorParseo,
    EtapaDocumento,
    es_reintentable,
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
        "formato_no_soportado",
        # openspec `paralelismo-de-procesamiento` PR 3, revisión adversarial
        # ALTO 3: deliberadamente distinto de `error_transitorio_agotado`
        # -- ver `trabajadores/despacho_paralelo.py`.
        "proceso_interrumpido",
        # Distinguen, dentro de lo que antes era un único `parseo_incompleto`
        # indistinguible, dos causas con acción operativa completamente
        # distinta (ver `extraccion/texto_pymupdf.py`): un escaneo necesita
        # OCR, un archivo corrupto necesita pedirlo de nuevo al origen.
        "sin_capa_de_texto",
        "pdf_ilegible",
    }


def test_es_reintentable_es_la_unica_definicion_y_cubre_todo_el_catalogo() -> None:
    """`es_reintentable` (`dominio/errores.py`) es la ÚNICA fuente de verdad
    sobre qué código admite reintento -- ninguna otra capa (web, ingesta)
    puede mantener su propia lista. Centinela de completitud explícito, no un
    `default False`: enumera CADA miembro del catálogo a mano, así que un
    código nuevo que no se agregue acá rompe este test por `KeyError`, no
    queda clasificado por accidente.

    Determinísticos (reprocesar sin cambios da el mismo fallo):
    `TIPO_NO_RECONOCIDO`, `PARSEO_INCOMPLETO`, `CLAVE_PII_AMBIGUA`,
    `EVIDENCIA_AUSENTE`, `EVIDENCIA_AMBIGUA`, `VALOR_DISCREPANTE`,
    `COBERTURA_INCOMPLETA`, `COBERTURA_AMBIGUA`, `EPISODIO_AMBIGUO` (ambigua
    = requiere revisión manual, igual que `CLAVE_PII_AMBIGUA`),
    `ARTEFACTO_SOBRETAMANO`/`FORMATO_NO_SOPORTADO` (propiedad del archivo, no
    cambia sola), `SIN_CAPA_DE_TEXTO` (necesita OCR, no un reproceso) y
    `PDF_ILEGIBLE` (necesita pedir el archivo de nuevo, no reprocesarlo).

    Reintentables (el error original no era determinístico, o la evidencia
    que faltaba puede haber llegado): `CLAVE_PII_NO_RESUELTA`,
    `ERROR_TRANSITORIO_AGOTADO`, `EPISODIO_INCOMPLETO`, `PROCESO_INTERRUMPIDO`.
    """
    esperado = {
        CodigoErrorDocumento.TIPO_NO_RECONOCIDO: False,
        CodigoErrorDocumento.PARSEO_INCOMPLETO: False,
        CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA: True,
        CodigoErrorDocumento.CLAVE_PII_AMBIGUA: False,
        CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO: True,
        CodigoErrorDocumento.EVIDENCIA_AUSENTE: False,
        CodigoErrorDocumento.EVIDENCIA_AMBIGUA: False,
        CodigoErrorDocumento.VALOR_DISCREPANTE: False,
        CodigoErrorDocumento.COBERTURA_INCOMPLETA: False,
        CodigoErrorDocumento.COBERTURA_AMBIGUA: False,
        CodigoErrorDocumento.EPISODIO_INCOMPLETO: True,
        CodigoErrorDocumento.EPISODIO_AMBIGUO: False,
        CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO: False,
        CodigoErrorDocumento.FORMATO_NO_SOPORTADO: False,
        CodigoErrorDocumento.PROCESO_INTERRUMPIDO: True,
        CodigoErrorDocumento.SIN_CAPA_DE_TEXTO: False,
        CodigoErrorDocumento.PDF_ILEGIBLE: False,
    }
    # Si el catálogo ganó un miembro nuevo sin actualizar `esperado`, este
    # `assert` explota ANTES del loop de abajo -- más legible que un
    # `KeyError` a mitad de iteración.
    assert {miembro for miembro in CodigoErrorDocumento} == set(esperado)
    for codigo, reintentable in esperado.items():
        assert es_reintentable(codigo) is reintentable, codigo.value


def test_detalle_parseo_incompleto_es_vocabulario_cerrado() -> None:
    """Las seis causas de `PARSEO_INCOMPLETO` que hoy comparten código pero
    ameritan una acción distinta (ver `parseo/ecg_mortara.py`,
    `parseo/eco_doppler.py`, `parseo/laboratorio_general.py`)."""
    detalles = {miembro.value for miembro in DetalleParseoIncompleto}
    assert detalles == {
        "header_ausente",
        "nombre_ausente",
        "fecha_ausente",
        "fecha_ilegible",
        "hora_ilegible",
        "numero_peticion_inconsistente",
    }


def test_error_documento_admite_detalle_parseo_incompleto() -> None:
    error = ErrorDocumento(
        id_documento="doc-001",
        etapa="parseo",
        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
        detalle_parseo=DetalleParseoIncompleto.NOMBRE_AUSENTE,
    )
    assert error.detalle_parseo is DetalleParseoIncompleto.NOMBRE_AUSENTE


def test_error_documento_rechaza_detalle_parseo_como_texto_libre() -> None:
    """Centinela de la invariante "sin PII en cola, logs ni DLQ": `detalle_parseo`
    es un vocabulario cerrado (enum), nunca un string arbitrario -- ni siquiera
    uno que luzca inocuo. Si esto aceptara `str`, cualquier llamador futuro
    podría filtrar un nombre de paciente o un fragmento del documento acá."""
    with pytest.raises(ValueError):
        ErrorDocumento(
            id_documento="doc-001",
            etapa="parseo",
            codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
            detalle_parseo="paciente juan perez, dni 12345678",  # type: ignore[arg-type]
        )


def test_error_documento_rechaza_detalle_parseo_fuera_de_parseo_incompleto() -> None:
    """`detalle_parseo` es exclusivo de `PARSEO_INCOMPLETO` (mismo precedente
    que `tamano_bytes`/`tope_bytes`, exclusivos de `ARTEFACTO_SOBRETAMANO`)."""
    with pytest.raises(ValueError):
        ErrorDocumento(
            id_documento="doc-001",
            etapa="parseo",
            codigo=CodigoErrorDocumento.TIPO_NO_RECONOCIDO,
            detalle_parseo=DetalleParseoIncompleto.NOMBRE_AUSENTE,
        )


def test_error_parseo_transporta_detalle_parseo_incompleto() -> None:
    excepcion = ErrorParseo(
        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
        etapa="parseo",
        detalle_parseo=DetalleParseoIncompleto.FECHA_ILEGIBLE,
    )
    assert excepcion.detalle_parseo is DetalleParseoIncompleto.FECHA_ILEGIBLE


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


def test_error_documento_acepta_corrida_id() -> None:
    """Requisito: `cuarentena` MUST llevar el identificador de la corrida que
    lo produjo (spec `trazabilidad-por-corrida`, Requisito 1)."""
    error = ErrorDocumento(
        id_documento="doc-001",
        etapa="parseo",
        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
        corrida_id="corrida-sintetica-1",
    )
    assert error.corrida_id == "corrida-sintetica-1"


def test_error_documento_sin_corrida_id_usa_default_none() -> None:
    # no debe romper fixtures existentes de otras fases que no la pasan
    error = ErrorDocumento(
        id_documento="doc-001",
        etapa="parseo",
        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
    )
    assert error.corrida_id is None


def test_error_parseo_transporta_solo_campo_y_pagina_seguros() -> None:
    error = ErrorParseo(
        codigo=CodigoErrorDocumento.EVIDENCIA_AUSENTE,
        etapa=EtapaDocumento.RECONCILIACION,
        campo="ecg.vent_rate",
        pagina=1,
    )
    assert error.campo == "ecg.vent_rate"
    assert error.pagina == 1
