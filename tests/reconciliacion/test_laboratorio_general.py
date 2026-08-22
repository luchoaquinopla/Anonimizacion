from datetime import date

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio, ResultadoLaboratorio
from anonimizacion.reconciliacion.base import ReferenciaCampo
from anonimizacion.reconciliacion.laboratorio_general import ReconciliadorLaboratorioGeneral


def _documento(resultados: tuple[ResultadoLaboratorio, ...], fuentes: tuple[ReferenciaCampo, ...]) -> DocumentoParseado:
    return DocumentoParseado(TipoDocumento.LABORATORIO, 1, IdentidadCruda(nombre=SecretStr("Persona Sintetica")), date(2025, 1, 10), ContenidoLaboratorio("900", resultados), fuentes=fuentes)


def test_reconcilia_resultados_repetidos_por_ordinal() -> None:
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "Prueba A", "10,5", "u", None), ResultadoLaboratorio("HEMATOLOGIA", "Prueba B", "12", "u", None))
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0), ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 1))
    ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), TextoExtraido(("Prueba A 10.5 u\nPrueba B 12 u",)))


def test_rechaza_resultado_laboratorio_discrepante() -> None:
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "Prueba A", "10", "u", None),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado"),)
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), TextoExtraido(("Prueba A 11 u",)))
    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE


def test_laboratorio_reconcilia_con_texto_ordenado() -> None:
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "Prueba A", "10", "u", None),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado"),)
    texto = TextoExtraido(("Prueba A\n10\nu",), ("Prueba A 10 u",))
    ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)


def test_laboratorio_asocia_resultado_sin_confundirlo_con_subcadena_del_numero_de_peticion() -> None:
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "Glucosa", "90", "mg/dL", "70-110"),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado"),)
    texto = TextoExtraido((
        "No Peticion: 900\nHEMATOLOGIA\nGlucosa | 90 | mg/dL | 70-110",
    ))

    ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)


def test_inventario_laboratorio_enumera_filas_por_seccion_y_ordinal() -> None:
    texto = TextoExtraido((
        "HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16\n"
        "HEMOSTASIA\nTP | 11 | s | 10 - 13",
    ))

    inventario = ReconciliadorLaboratorioGeneral().inventariar(texto)

    assert [(hallazgo.id_campo, hallazgo.pagina, hallazgo.ordinal, hallazgo.clase) for hallazgo in inventario] == [
        ("laboratorio.resultado", 1, 0, "coleccion"),
        ("laboratorio.resultado", 1, 1, "coleccion"),
    ]


def test_laboratorio_rechaza_fila_inventariada_omitida_por_el_parseo() -> None:
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "Hemoglobina", "14,2", "g/dL", "12 - 16"),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),)
    texto = TextoExtraido((
        "HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16\n"
        "HEMOSTASIA\nTP | 11 | s | 10 - 13",
    ))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA
    assert error.value.campo == "laboratorio.resultado"


def test_laboratorio_rechaza_unidad_asociada_incorrectamente() -> None:
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "Hemoglobina", "14,2", "mmol/L", "12 - 16"),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),)

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(
            _documento(filas, fuentes),
            TextoExtraido(("HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16",)),
        )

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE


def test_laboratorio_rechaza_seccion_asociada_incorrectamente() -> None:
    filas = (ResultadoLaboratorio("HEMOSTASIA", "Hemoglobina", "14,2", "g/dL", "12 - 16"),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),)

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(
            _documento(filas, fuentes),
            TextoExtraido(("HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16",)),
        )

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE


def test_laboratorio_rechaza_ordinal_de_destino_repetido() -> None:
    filas = (
        ResultadoLaboratorio("HEMATOLOGIA", "Hemoglobina", "14,2", "g/dL", "12 - 16"),
        ResultadoLaboratorio("HEMATOLOGIA", "Hematocrito", "42", "%", "36 - 46"),
    )
    fuentes = (
        ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),
        ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),
    )
    texto = TextoExtraido((
        "HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16\n"
        "Hematocrito | 42 | % | 36 - 46",
    ))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_AMBIGUA


def test_laboratorio_conserva_subseccion_para_validar_asociacion() -> None:
    filas = (ResultadoLaboratorio("HEMOGRAMA", "Hemoglobina", "14,2", "g/dL", "12 - 16"),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),)
    texto = TextoExtraido(("HEMATOLOGIA\nHEMOGRAMA\nHemoglobina | 14,2 | g/dL | 12 - 16",))

    ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)


def test_laboratorio_rechaza_referencia_en_pagina_incorrecta_con_valor_repetido() -> None:
    filas = (
        ResultadoLaboratorio("HEMATOLOGIA", "Hemoglobina", "14,2", "g/dL", "12 - 16"),
        ResultadoLaboratorio("HEMOSTASIA", "TP", "14,2", "s", "10 - 13"),
    )
    fuentes = (
        ReferenciaCampo("laboratorio.resultado", 2, "laboratorio.resultado", 0),
        ReferenciaCampo("laboratorio.resultado", 2, "laboratorio.resultado", 1),
    )
    texto = TextoExtraido((
        "HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16",
        "HEMOSTASIA\nTP | 14,2 | s | 10 - 13",
    ))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_laboratorio_no_inventaria_el_header_de_una_pagina_posterior() -> None:
    texto = TextoExtraido((
        "HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16",
        "Fecha: 10/01/2025  Hora: 09:00",
    ))

    inventario = ReconciliadorLaboratorioGeneral().inventariar(texto)

    assert [(hallazgo.pagina, hallazgo.ordinal) for hallazgo in inventario] == [(1, 0)]


def test_laboratorio_conserva_seccion_en_una_tabla_que_continua_en_la_pagina_siguiente() -> None:
    texto = TextoExtraido((
        "HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16",
        "Fecha: 10/01/2025  Hora: 09:00\nHematocrito | 40 | % | 36 - 46",
    ))

    inventario = ReconciliadorLaboratorioGeneral().inventariar(texto)

    assert [(hallazgo.pagina, hallazgo.ordinal) for hallazgo in inventario] == [(1, 0), (2, 1)]


def test_laboratorio_reconstruye_nombre_partido_antes_de_asociar_fila() -> None:
    filas = (
        ResultadoLaboratorio(
            "QUIMICA CLINICA",
            "Filtrado Glomerular Estimado (CKD-EPI 2021)",
            "102",
            "mL/min/1.73m2",
            None,
        ),
    )
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),)
    texto = TextoExtraido((
        "QUIMICA CLINICA\n"
        "Filtrado Glomerular Estimado (CKD-EPI  102  mL/min/1.73m2\n"
        "2021)",
    ))

    ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)


def test_laboratorio_inventaria_resultado_cualitativo_omitido() -> None:
    texto = TextoExtraido(("HEMATOLOGIA\nSARS-CoV-2  NEGATIVO",))
    documento = _documento((), ())

    assert ReconciliadorLaboratorioGeneral().inventariar(texto)[0].id_campo == "laboratorio.resultado"
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_laboratorio_valida_resultado_cualitativo_con_destino() -> None:
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "SARS-CoV-2", "NO DETECTADO", None, None),)
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),)
    texto = TextoExtraido(("HEMATOLOGIA\nSARS-CoV-2  NO DETECTADO",))

    ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)


def test_laboratorio_inventaria_fila_cualitativa_pipe_fuera_de_allowlist() -> None:
    texto = TextoExtraido(("HEMATOLOGIA\nSARS-CoV-2 | INDETERMINADO",))
    documento = _documento((), ())

    assert ReconciliadorLaboratorioGeneral().inventariar(texto)[0].id_campo == "laboratorio.resultado"
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_laboratorio_no_reconstruye_nombre_partido_en_formato_pipe() -> None:
    filas = (
        ResultadoLaboratorio("QUIMICA CLINICA", "Filtrado Glomerular Estimado (CKD-EPI", "102", "mL/min", None),
    )
    fuentes = (ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),)
    texto = TextoExtraido((
        "QUIMICA CLINICA\n"
        "Filtrado Glomerular Estimado (CKD-EPI | 102 | mL/min\n"
        "2021)",
    ))

    ReconciliadorLaboratorioGeneral().reconciliar(_documento(filas, fuentes), texto)


def test_laboratorio_inventaria_cualitativo_abierto_en_formato_real_omitido() -> None:
    texto = TextoExtraido(("HEMATOLOGIA\nSARS-CoV-2  INDETERMINADO",))
    documento = _documento((), ())

    assert ReconciliadorLaboratorioGeneral().inventariar(texto)[0].id_campo == "laboratorio.resultado"
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_laboratorio_no_inventaria_encabezado_de_dos_columnas() -> None:
    texto = TextoExtraido(("HEMATOLOGIA\nPruebas  Resultado",))

    assert ReconciliadorLaboratorioGeneral().inventariar(texto) == ()


def test_whitelist_laboratorio_ignora_solo_encabezado_de_columnas() -> None:
    reconciliador = ReconciliadorLaboratorioGeneral()

    assert reconciliador.es_texto_permitido("Pruebas  Resultado Actual  Unidades  Valores de Referencia")
    assert not reconciliador.es_texto_permitido("Hemoglobina | 14,2 | g/dL | 12 - 16")
