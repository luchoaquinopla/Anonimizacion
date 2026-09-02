import re
from datetime import date, time

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.reconciliacion.base import HallazgoCobertura, ReferenciaCampo
from anonimizacion.reconciliacion.ecg_mortara import ReconciliadorEcgMortara
from anonimizacion.reconciliacion.inventario import verificar_cobertura


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
    ReconciliadorEcgMortara().reconciliar(documento, TextoExtraido(("12-DEC-1975 (49 yr)",)))


def test_rechaza_medidas_ecg_asignadas_a_etiquetas_cruzadas() -> None:
    fuentes = (
        ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate"),
        ReferenciaCampo("ecg.pr_interval", 1, "ecg.pr_interval"),
    )
    documento = DocumentoParseado(
        TipoDocumento.ECG,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 6, 5),
        ContenidoEcg("120", "160", None, None, None),
        fuentes=fuentes,
    )

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcgMortara().reconciliar(
            documento,
            TextoExtraido(("Vent. rate 160\nPR interval 120",)),
        )

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE
    assert error.value.campo == "ecg.vent_rate"


def test_aprueba_medida_ecg_en_linea_vecina_a_su_etiqueta() -> None:
    fuente = ReferenciaCampo("ecg.pr_interval", 1, "ecg.pr_interval")
    documento = DocumentoParseado(
        TipoDocumento.ECG,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 6, 5),
        ContenidoEcg(None, "160", None, None, None),
        fuentes=(fuente,),
    )

    ReconciliadorEcgMortara().reconciliar(
        documento,
        TextoExtraido(("160\nPR interval",)),
    )


def test_aprueba_medida_asociada_aunque_el_numero_aparezca_en_otro_campo() -> None:
    fuente = ReferenciaCampo("ecg.vent_rate", 1, "ecg.vent_rate")
    documento = _documento("68", (fuente,))

    ReconciliadorEcgMortara().reconciliar(
        documento,
        TextoExtraido(("Codigo auxiliar 6800\nVent. rate 68",)),
    )


_HEADER_CON_TIMESTAMP = (
    "Persona Sintetica~, ID:ESTUDIO-1 05-JUN-2025 10:22:31 INSTITUTO FICTICIO ROUTINE RECORD"
)


def test_ecg_hora_estudio_sin_patron_de_inventario_produce_cobertura_incompleta() -> None:
    """Gotcha 1 (design.md, decisión 4): agregar el `id_campo` `ecg.hora_estudio`
    a la whitelist sin su patrón de inventario correspondiente debe fijarse
    como `COBERTURA_INCOMPLETA` -- documenta el comportamiento ANTES de
    agregar el patrón anclado (task 4.4)."""
    fuente = ReferenciaCampo("ecg.hora_estudio", 1, "ecg.hora_estudio")
    inventario_sin_patron_de_hora: tuple[HallazgoCobertura, ...] = ()

    with pytest.raises(ErrorParseo) as error:
        verificar_cobertura(inventario_sin_patron_de_hora, (fuente,))

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_patron_de_hora_suelto_produce_cobertura_ambigua_contra_header_real() -> None:
    """Gotcha 1 (design.md, decisión 4): un patrón de inventario SUELTO
    (`\\d{2}:\\d{2}:\\d{2}`, sin anclar al timestamp `DD-MON-YYYY HH:MM:SS`
    completo) matchea más de una vez en un documento real que trae otra hora
    suelta en otra parte del header (p. ej. una hora de impresión) -- produce
    `COBERTURA_AMBIGUA` en vez de identificar sin ambigüedad la hora del
    estudio. Este test documenta el gotcha directamente contra
    `verificar_cobertura`, sin pasar por el patrón real ya anclado que usa
    `ReconciliadorEcgMortara` (Fase 4, GREEN)."""
    header_con_segunda_hora_suelta = (
        _HEADER_CON_TIMESTAMP + "\nImpreso a las 09:15:00 por el equipo"
    )
    patron_suelto = re.compile(r"\d{2}:\d{2}:\d{2}")
    hallazgos = tuple(
        HallazgoCobertura("ecg.hora_estudio", 1, clase="header")
        for _coincidencia in patron_suelto.finditer(header_con_segunda_hora_suelta)
    )
    assert len(hallazgos) == 2  # la hora del estudio + la hora de impresión

    with pytest.raises(ErrorParseo) as error:
        verificar_cobertura(hallazgos, (ReferenciaCampo("ecg.hora_estudio", 1, "ecg.hora_estudio"),))

    assert error.value.codigo is CodigoErrorDocumento.COBERTURA_AMBIGUA


_FUENTES_HEADER_CON_TIMESTAMP = (
    ReferenciaCampo("ecg.nombre", 1, "ecg.nombre"),
    ReferenciaCampo("ecg.id_estudio", 1, "ecg.id_estudio"),
    ReferenciaCampo("ecg.fecha_estudio", 1, "ecg.fecha_estudio"),
    ReferenciaCampo("ecg.hora_estudio", 1, "ecg.hora_estudio"),
)


def test_reconcilia_hora_estudio_anclada_al_timestamp_completo() -> None:
    """GREEN de la Fase 4: con el patrón anclado al timestamp completo (mismo
    grupo que `ecg.fecha_estudio`), la hora reconcilia sin ambigüedad."""
    documento = DocumentoParseado(
        TipoDocumento.ECG,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica"), ids_internos=(SecretStr("ESTUDIO-1"),)),
        date(2025, 6, 5),
        ContenidoEcg(None, None, None, None, None),
        fuentes=_FUENTES_HEADER_CON_TIMESTAMP,
        hora_estudio=time(10, 22, 31),
    )

    ReconciliadorEcgMortara().reconciliar(documento, TextoExtraido((_HEADER_CON_TIMESTAMP,)))


def test_rechaza_hora_estudio_discrepante() -> None:
    documento = DocumentoParseado(
        TipoDocumento.ECG,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica"), ids_internos=(SecretStr("ESTUDIO-1"),)),
        date(2025, 6, 5),
        ContenidoEcg(None, None, None, None, None),
        fuentes=_FUENTES_HEADER_CON_TIMESTAMP,
        hora_estudio=time(11, 0, 0),
    )

    with pytest.raises(ErrorParseo) as error:
        ReconciliadorEcgMortara().reconciliar(documento, TextoExtraido((_HEADER_CON_TIMESTAMP,)))

    assert error.value.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE
    assert error.value.campo == "ecg.hora_estudio"


def test_aprueba_ejes_ecg_en_lineas_posteriores_a_la_etiqueta() -> None:
    fuente = ReferenciaCampo("ecg.ejes", 1, "ecg.ejes")
    documento = DocumentoParseado(
        TipoDocumento.ECG,
        1,
        IdentidadCruda(nombre=SecretStr("Persona Sintetica")),
        date(2025, 6, 5),
        ContenidoEcg(None, None, None, None, "10 20 30"),
        fuentes=(fuente,),
    )

    ReconciliadorEcgMortara().reconciliar(
        documento,
        TextoExtraido(("P-R-T axes\n10\n20\n30",)),
    )
