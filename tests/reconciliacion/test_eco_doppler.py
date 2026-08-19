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
