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
