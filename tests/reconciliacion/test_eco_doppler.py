from datetime import date

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.eco_doppler import ContenidoEco, FirmaMedico, MedidaEco, SeccionTextoEco
from anonimizacion.reconciliacion.base import ReferenciaCampo
from anonimizacion.reconciliacion.eco_doppler import ReconciliadorEcoDoppler


def _documento(fuentes: tuple[ReferenciaCampo, ...]) -> DocumentoParseado:
    contenido = ContenidoEco((MedidaEco("AO", "28", "mm"),), (SeccionTextoEco("CONCLUSIONES", "Estudio normal."),), None)
    return DocumentoParseado(TipoDocumento.ECOCARDIOGRAMA, 1, IdentidadCruda(nombre=SecretStr("Persona Sintetica")), date(2025, 3, 20), contenido, fuentes=fuentes)


def test_reconcilia_medida_y_texto_del_eco() -> None:
    fuentes = (ReferenciaCampo("eco.medida", 1, "eco.medida.ao", 0), ReferenciaCampo("eco.seccion", 1, "eco.seccion", 0))
    ReconciliadorEcoDoppler().reconciliar(_documento(fuentes), TextoExtraido(("AO 28 mm\nCONCLUSIONES\nEstudio normal.",)))


def test_rechaza_referencia_eco_sin_destino() -> None:
    fuente = ReferenciaCampo("eco.medida", 1, "eco.medida.ao", 1)
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(_documento((fuente,)), TextoExtraido(("AO 28 mm",)))
    assert error.value.codigo is CodigoErrorDocumento.EVIDENCIA_AUSENTE


def test_reconcilia_firma_del_informante_cuando_existe() -> None:
    from anonimizacion.parseo.eco_doppler import FirmaMedico

    fuente = ReferenciaCampo("eco.firma", 1, "eco.firma")
    documento = _documento((fuente,))
    contenido = ContenidoEco(documento.contenido.medidas, documento.contenido.secciones_texto, FirmaMedico("Medico Sintetico", "MP 99"))
    documento = DocumentoParseado(documento.tipo_documento, 1, documento.identidad, documento.fecha_estudio, contenido, fuentes=(fuente,))
    ReconciliadorEcoDoppler().reconciliar(documento, TextoExtraido(("Medico Sintetico MP 99",)))


def test_reconcilia_firma_legada_y_numero_estudio() -> None:
    from anonimizacion.parseo.eco_doppler import FirmaMedico
    fuentes = (ReferenciaCampo("eco.firma", 1, "eco.firma"), ReferenciaCampo("eco.numero_estudio", 1, "eco.numero_estudio"))
    contenido = ContenidoEco((), (), FirmaMedico("Medico Sintetico", "99"))
    documento = DocumentoParseado(TipoDocumento.ECOCARDIOGRAMA, 1, IdentidadCruda(nombre=SecretStr("Persona"), ids_internos=(SecretStr("E-1"),)), date(2025, 3, 20), contenido, fuentes=fuentes)
    ReconciliadorEcoDoppler().reconciliar(documento, TextoExtraido(("Firma: Medico Sintetico - MP 99\nNº Estudio: E-1",)))


def test_inventaria_headers_medidas_secciones_y_firma_en_paginas_reales() -> None:
    texto = TextoExtraido((
        "Paciente: Persona Sintetica\nFecha Estudio: 20/03/2025\nMEDIDAS\nAO | 28 | mm\nCONCLUSIONES\nPrimera conclusion.",
        "MEDIDAS\nAI | 32 | mm\nPERICARDIO\nSin derrame.\nFirma: Medico Sintetico - MP 99",
    ))

    inventario = ReconciliadorEcoDoppler().inventariar(texto)

    assert [(hallazgo.id_campo, hallazgo.pagina, hallazgo.ordinal) for hallazgo in inventario] == [
        ("eco.nombre", 1, 0),
        ("eco.fecha_estudio", 1, 0),
        ("eco.medida", 1, 0),
        ("eco.seccion", 1, 0),
        ("eco.medida", 2, 1),
        ("eco.seccion", 2, 1),
        ("eco.firma", 2, 0),
    ]


def test_rechaza_medida_omitida_del_modelo_aunque_el_valor_emitido_exista() -> None:
    fuentes = (ReferenciaCampo("eco.medida", 1, "eco.medida.ao", 0),)
    documento = DocumentoParseado(
        TipoDocumento.ECOCARDIOGRAMA,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 3, 20),
        ContenidoEco((MedidaEco("AO", "28", "mm"),), (), None),
        fuentes=fuentes,
    )
    texto = TextoExtraido(("MEDIDAS\nAO 28 mm\nAI 32 mm",))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA
    assert error.value.campo == "eco.medida"
    assert error.value.pagina == 1


def test_rechaza_seccion_omitida_en_otra_pagina() -> None:
    fuentes = (ReferenciaCampo("eco.seccion", 1, "eco.seccion", 0),)
    documento = DocumentoParseado(
        TipoDocumento.ECOCARDIOGRAMA,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 3, 20),
        ContenidoEco((), (SeccionTextoEco("CONCLUSIONES", "Primera conclusion."),), None),
        fuentes=fuentes,
    )
    texto = TextoExtraido(("CONCLUSIONES\nPrimera conclusion.", "PERICARDIO\nSin derrame."))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA
    assert error.value.campo == "eco.seccion"
    assert error.value.pagina == 2


def test_rechaza_referencia_de_eco_en_pagina_distinta_a_su_inventario() -> None:
    fuentes = (ReferenciaCampo("eco.medida", 2, "eco.medida.ao", 0),)
    documento = DocumentoParseado(
        TipoDocumento.ECOCARDIOGRAMA,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 3, 20),
        ContenidoEco((MedidaEco("AO", "28", "mm"),), (), None),
        fuentes=fuentes,
    )
    texto = TextoExtraido(("MEDIDAS\nAO 28 mm", "AO 28 mm"))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA
    assert error.value.campo == "eco.medida"
    assert error.value.pagina == 1


def test_rechaza_texto_de_seccion_asociado_a_etiqueta_distinta() -> None:
    fuente = ReferenciaCampo("eco.seccion", 1, "eco.seccion", 0)
    documento = DocumentoParseado(
        TipoDocumento.ECOCARDIOGRAMA,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 3, 20),
        ContenidoEco((), (SeccionTextoEco("PERICARDIO", "Sin derrame."),), None),
        fuentes=(fuente,),
    )

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(documento, TextoExtraido(("CONCLUSIONES\nSin derrame.",)))

    assert error.value.codigo is CodigoErrorDocumento.EVIDENCIA_AUSENTE


def test_reconcilia_medida_del_parser_en_formato_pipe() -> None:
    from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler

    texto = TextoExtraido((
        "Paciente: Persona Sintetica\nFecha Estudio: 20/03/2025\nMEDIDAS\nAO | 28 | mm",
    ))
    documento = ParseadorEcoDoppler().parsear(texto)

    ReconciliadorEcoDoppler().reconciliar(documento, texto)


def test_reconcilia_tabla_real_de_medidas_en_dos_columnas() -> None:
    from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler

    texto = TextoExtraido((
        "Paciente: Persona Sintetica\n"
        "Fecha Estudio: 20/03/2025\n"
        "MEDIDAS    VALOR    VALOR NORMAL    MEDIDAS    VALOR    VALOR NORMAL\n"
        "XX    10 mm    < 20 mm    YY    5 mm    < 9 mm",
    ))
    documento = ParseadorEcoDoppler().parsear(texto)

    ReconciliadorEcoDoppler().reconciliar(documento, texto)


def test_emite_selector_especifico_por_etiqueta_en_tabla_de_dos_columnas() -> None:
    from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler

    texto = TextoExtraido((
        "Paciente: Persona Sintetica\n"
        "Fecha Estudio: 20/03/2025\n"
        "MEDIDAS    VALOR    VALOR NORMAL    MEDIDAS    VALOR    VALOR NORMAL\n"
        "AO    10 mm    < 20 mm    AI    10 mm    < 20 mm",
    ))

    documento = ParseadorEcoDoppler().parsear(texto)

    assert [referencia.selector for referencia in documento.fuentes if referencia.id_campo == "eco.medida"] == [
        "eco.medida.ao",
        "eco.medida.ai",
    ]


def test_rechaza_medidas_iguales_asignadas_a_selectores_cruzados_en_dos_columnas() -> None:
    contenido = ContenidoEco((MedidaEco("AO", "10", "mm"), MedidaEco("AI", "10", "mm")), (), None)
    documento = DocumentoParseado(
        TipoDocumento.ECOCARDIOGRAMA,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 3, 20),
        contenido,
        fuentes=(
            ReferenciaCampo("eco.medida", 1, "eco.medida.ai", 0),
            ReferenciaCampo("eco.medida", 1, "eco.medida.ao", 1),
        ),
    )
    texto = TextoExtraido((
        "MEDIDAS    VALOR    VALOR NORMAL    MEDIDAS    VALOR    VALOR NORMAL\n"
        "AO    10 mm    < 20 mm    AI    10 mm    < 20 mm",
    ))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(documento, texto)

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE
    assert error.value.campo == "eco.medida"


def test_reconcilia_etiqueta_de_medida_con_espacio_y_puntuacion() -> None:
    contenido = ContenidoEco((MedidaEco("P. Posterior", "8", "mm"),), (), None)
    documento = DocumentoParseado(
        TipoDocumento.ECOCARDIOGRAMA,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 3, 20),
        contenido,
        fuentes=(ReferenciaCampo("eco.medida", 1, "eco.medida.p.posterior", 0),),
    )

    ReconciliadorEcoDoppler().reconciliar(documento, TextoExtraido(("MEDIDAS\nP. Posterior 8 mm",)))


def test_rechaza_nombre_eco_asignado_a_otro_lugar_del_documento() -> None:
    fuente = ReferenciaCampo("eco.nombre", 1, "eco.nombre")
    documento = _documento((fuente,))

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(
            documento,
            TextoExtraido(("Paciente: Otra Persona\nMEDIDAS\nPersona Sintetica",)),
        )

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE
    assert error.value.campo == "eco.nombre"


def test_aprueba_nombre_eco_en_su_header() -> None:
    fuente = ReferenciaCampo("eco.nombre", 1, "eco.nombre")
    documento = _documento((fuente,))

    ReconciliadorEcoDoppler().reconciliar(
        documento,
        TextoExtraido(("Paciente: Persona Sintetica\nMEDIDAS",)),
    )


def test_rechaza_firma_esperada_disgregada_junto_a_otra_firma() -> None:
    fuente = ReferenciaCampo("eco.firma", 1, "eco.firma")
    documento_base = _documento((fuente,))
    documento = DocumentoParseado(
        documento_base.tipo_documento,
        documento_base.version_esquema,
        documento_base.identidad,
        documento_base.fecha_estudio,
        ContenidoEco((), (), FirmaMedico("Medico Esperado", "W 99")),
        fuentes=(fuente,),
    )

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(
            documento,
            TextoExtraido(("Medico Esperado\nFirma: Otro Medico - MP 12\nTexto intermedio\nMatrícula W 99",)),
        )

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE
    assert error.value.campo == "eco.firma"


def test_aprueba_firma_real_en_lineas_separadas() -> None:
    fuente = ReferenciaCampo("eco.firma", 1, "eco.firma")
    documento_base = _documento((fuente,))
    documento = DocumentoParseado(
        documento_base.tipo_documento,
        documento_base.version_esquema,
        documento_base.identidad,
        documento_base.fecha_estudio,
        ContenidoEco((), (), FirmaMedico("Medico Sintetico", "W 6707")),
        fuentes=(fuente,),
    )

    ReconciliadorEcoDoppler().reconciliar(
        documento,
        TextoExtraido(("MEDICO SINTETICO\nMatrícula W 6707",)),
    )


def test_aprueba_firma_real_con_linea_intermedia_antes_de_la_matricula() -> None:
    fuente = ReferenciaCampo("eco.firma", 1, "eco.firma")
    documento_base = _documento((fuente,))
    documento = DocumentoParseado(
        documento_base.tipo_documento,
        documento_base.version_esquema,
        documento_base.identidad,
        documento_base.fecha_estudio,
        ContenidoEco((), (), FirmaMedico("Medico Sintetico", "W 6707")),
        fuentes=(fuente,),
    )

    ReconciliadorEcoDoppler().reconciliar(
        documento,
        TextoExtraido(("MEDICO SINTETICO\nEspecialista en cardiologia\nMatrícula W 6707",)),
    )


def test_rechaza_matricula_posterior_separada_por_firma_legada_de_otro_medico() -> None:
    fuente = ReferenciaCampo("eco.firma", 1, "eco.firma")
    documento_base = _documento((fuente,))
    documento = DocumentoParseado(
        documento_base.tipo_documento,
        documento_base.version_esquema,
        documento_base.identidad,
        documento_base.fecha_estudio,
        ContenidoEco((), (), FirmaMedico("Medico Esperado", "W 99")),
        fuentes=(fuente,),
    )

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcoDoppler().reconciliar(
            documento,
            TextoExtraido(("Medico Esperado\nOtro Medico MP 12\nTexto intermedio\nMatrícula W 99",)),
        )

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE
    assert error.value.campo == "eco.firma"
