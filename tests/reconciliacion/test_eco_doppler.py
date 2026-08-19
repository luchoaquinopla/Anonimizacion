from datetime import date

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.eco_doppler import ContenidoEco, MedidaEco, SeccionTextoEco
from anonimizacion.reconciliacion.base import ReferenciaCampo
from anonimizacion.reconciliacion.eco_doppler import ReconciliadorEcoDoppler


def _documento(fuentes: tuple[ReferenciaCampo, ...]) -> DocumentoParseado:
    contenido = ContenidoEco((MedidaEco("AO", "28", "mm"),), (SeccionTextoEco("CONCLUSIONES", "Estudio normal."),), None)
    return DocumentoParseado(TipoDocumento.ECOCARDIOGRAMA, 1, IdentidadCruda(nombre=SecretStr("Persona Sintetica")), date(2025, 3, 20), contenido, fuentes=fuentes)


def test_reconcilia_medida_y_texto_del_eco() -> None:
    fuentes = (ReferenciaCampo("eco.medida", 1, "eco.medida", 0), ReferenciaCampo("eco.seccion", 1, "eco.seccion", 0))
    ReconciliadorEcoDoppler().reconciliar(_documento(fuentes), TextoExtraido(("AO 28 mm\nCONCLUSIONES\nEstudio normal.",)))


def test_rechaza_referencia_eco_sin_destino() -> None:
    fuente = ReferenciaCampo("eco.medida", 1, "eco.medida", 1)
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
    fuentes = (ReferenciaCampo("eco.medida", 1, "eco.medida", 0),)
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
    fuentes = (ReferenciaCampo("eco.medida", 2, "eco.medida", 0),)
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
