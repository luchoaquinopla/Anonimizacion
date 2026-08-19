from datetime import date

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.reconciliacion.base import ReferenciaCampo
from anonimizacion.reconciliacion.ecg_mortara import ReconciliadorEcgMortara


def _documento(valor: str = "68 BPM", fuentes: tuple[ReferenciaCampo, ...] = ()) -> DocumentoParseado:
    return DocumentoParseado(TipoDocumento.ECG, 1, IdentidadCruda(nombre=SecretStr("Persona Sintetica")), date(2025, 6, 5), ContenidoEcg(valor, None, None, None, None), fuentes=fuentes)


def test_aprueba_medida_ecg_con_espacios_equivalentes() -> None:
    fuente = ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate")
    ReconciliadorEcgMortara().reconciliar(_documento(fuentes=(fuente,)), TextoExtraido(("Vent. rate  68   BPM",)))


@pytest.mark.parametrize(("valor", "texto", "codigo"), [("68 BPM", "Vent. rate 70 BPM", CodigoErrorDocumento.VALOR_DISCREPANTE), ("68 BPM", "sin medida", CodigoErrorDocumento.EVIDENCIA_AUSENTE)])
def test_rechaza_discrepancia_o_ausencia_ecg(valor: str, texto: str, codigo: CodigoErrorDocumento) -> None:
    fuente = ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate")
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcgMortara().reconciliar(_documento(valor, (fuente,)), TextoExtraido((texto,)))
    assert error.value.codigo is codigo


def test_rechaza_evidencia_ambigua_ecg() -> None:
    fuente = ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate")
    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcgMortara().reconciliar(_documento(fuentes=(fuente,)), TextoExtraido(("68 BPM\n68 BPM",)))
    assert error.value.codigo is CodigoErrorDocumento.EVIDENCIA_AMBIGUA


def test_reconcilia_fecha_nacimiento_ecg() -> None:
    fuente = ReferenciaCampo("ecg.fecha_nacimiento", 1, "ecg.fecha_nacimiento")
    documento = DocumentoParseado(TipoDocumento.ECG, 1, IdentidadCruda(nombre=SecretStr("Persona"), fecha_nac=SecretStr("1975-12-12")), date(2025, 6, 5), ContenidoEcg(None, None, None, None, None), fuentes=(fuente,))
    ReconciliadorEcgMortara().reconciliar(documento, TextoExtraido(("12-DEC-1975",)))
