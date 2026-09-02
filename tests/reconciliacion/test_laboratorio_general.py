from datetime import date, time

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio, ResultadoLaboratorio
from anonimizacion.reconciliacion._comun import reconciliar_referencias
from anonimizacion.reconciliacion.base import ReferenciaCampo
from anonimizacion.reconciliacion.laboratorio_general import ReconciliadorLaboratorioGeneral


def _documento(
    resultados: tuple[ResultadoLaboratorio, ...],
    fuentes: tuple[ReferenciaCampo, ...],
    *,
    hora_estudio: time | None = None,
    precision_hora: PrecisionHora = PrecisionHora.AUSENTE,
) -> DocumentoParseado:
    return DocumentoParseado(
        TipoDocumento.LABORATORIO,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 1, 10),
        ContenidoLaboratorio("900", resultados),
        fuentes=fuentes,
        hora_estudio=hora_estudio,
        precision_hora=precision_hora,
    )


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


def test_hora_extraccion_sin_validador_asociacion_rechaza_documento_legitimo() -> None:
    """Gotcha 2 (design.md, decisión 4, "la parte más frágil"): sin
    `validador_asociacion`, `reconciliar_referencias` cae en
    `pagina.count(valor) == 1` (`_comun.py:51`). Un valor de hora suelto que
    aparece más de una vez en la página (p. ej. coincide con otro valor no
    relacionado) rompe un documento legítimo. Este test reproduce el bug
    llamando `reconciliar_referencias` directamente, sin el
    `validador_asociacion` que agrega la Fase 6 (GREEN)."""
    fuente = ReferenciaCampo("laboratorio.hora_extraccion", 1, "laboratorio.hora_extraccion")
    documento = _documento((), (fuente,), hora_estudio=time(8, 30), precision_hora=PrecisionHora.MINUTO)
    # "08:30" aparece dos veces en la página: una vez tras el rótulo real, y
    # otra como coincidencia en un campo no relacionado.
    pagina = "Hora de Extraccion: 08:30\nCodigo interno 08:30 no relacionado"
    texto = TextoExtraido((pagina,))

    with pytest.raises(ErrorParseo) as error:
        reconciliar_referencias(documento, texto, {("laboratorio.hora_extraccion", 0): "08:30"})

    assert error.value.codigo is CodigoErrorDocumento.EVIDENCIA_AMBIGUA


def test_hora_extraccion_con_validador_asociacion_ancla_al_rotulo() -> None:
    """GREEN de la Fase 6: con `_asociacion_laboratorio` (anclado al rótulo
    `Hora de Extracción:`), el mismo documento del test anterior reconcilia
    sin error -- la hora se ancla a su rótulo, no a una coincidencia suelta."""
    from anonimizacion.reconciliacion.laboratorio_general import _asociacion_laboratorio

    fuente = ReferenciaCampo("laboratorio.hora_extraccion", 1, "laboratorio.hora_extraccion")
    documento = _documento((), (fuente,), hora_estudio=time(8, 30), precision_hora=PrecisionHora.MINUTO)
    pagina = "Hora de Extraccion: 08:30\nCodigo interno 08:30 no relacionado"
    texto = TextoExtraido((pagina,))

    reconciliar_referencias(
        documento,
        texto,
        {("laboratorio.hora_extraccion", 0): "08:30"},
        validador_asociacion=_asociacion_laboratorio,
    )


def test_reconciliador_laboratorio_reconcilia_hora_extraccion_end_to_end() -> None:
    """GREEN de la Fase 6: `ReconciliadorLaboratorioGeneral.reconciliar`
    reconcilia `laboratorio.hora_extraccion` de punta a punta, sin afectar
    la ruta existente de `laboratorio.resultado`."""
    filas = (ResultadoLaboratorio("HEMATOLOGIA", "Hemoglobina", "14,2", "g/dL", "12 - 16"),)
    fuentes = (
        ReferenciaCampo("laboratorio.hora_extraccion", 1, "laboratorio.hora_extraccion"),
        ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),
    )
    documento = _documento(filas, fuentes, hora_estudio=time(8, 30), precision_hora=PrecisionHora.MINUTO)
    texto = TextoExtraido((
        "Hora de Extraccion: 08:30\nHEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16",
    ))

    ReconciliadorLaboratorioGeneral().reconciliar(documento, texto)


def test_reconciliador_laboratorio_rechaza_hora_extraccion_discrepante() -> None:
    fuentes = (ReferenciaCampo("laboratorio.hora_extraccion", 1, "laboratorio.hora_extraccion"),)
    documento = _documento((), fuentes, hora_estudio=time(9, 0), precision_hora=PrecisionHora.MINUTO)
    texto = TextoExtraido(("Hora de Extraccion: 08:30",))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorLaboratorioGeneral().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE


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


def test_laboratorio_no_inventaria_numero_peticion_acentuado_en_pagina_posterior() -> None:
    texto = TextoExtraido((
        "HEMATOLOGIA\nHemoglobina | 14,2 | g/dL | 12 - 16",
        "Nº Petición:  REACTIVO",
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


def test_laboratorio_no_inventaria_narrativa_como_resultado_cualitativo() -> None:
    texto = TextoExtraido(("HEMATOLOGIA\nComentario general  Texto narrativo que no es un resultado",))

    assert ReconciliadorLaboratorioGeneral().inventariar(texto) == ()


def test_laboratorio_canonicaliza_alias_ionograma_y_conserva_asociacion_ordinal() -> None:
    filas = (
        ResultadoLaboratorio("HEMATOLOGIA", "Marcador", "REACTIVO", None, None),
        ResultadoLaboratorio("IONOGRAMA", "Sodio", "140", "mEq/L", "135 - 145"),
    )
    fuentes = (
        ReferenciaCampo("laboratorio.resultado", 1, "laboratorio.resultado", 0),
        ReferenciaCampo("laboratorio.resultado", 2, "laboratorio.resultado", 1),
    )
    texto = TextoExtraido((
        "HEMATOLOGIA\nMarcador  REACTIVO",
        "IONOGRAMA SERICO\nSodio  140  mEq/L  135 - 145",
    ))

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
