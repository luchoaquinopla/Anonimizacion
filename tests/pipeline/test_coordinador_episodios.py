from __future__ import annotations

from datetime import date

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pipeline.coordinador_episodios import (
    DocumentoParaCoordinar,
    MotivoCuarentenaEpisodio,
    coordinar_episodios,
)

_PEPPER = b"pepper-test-coordinador"


def _documento(id_documento: str, tipo: TipoDocumento, fecha: date) -> DocumentoParaCoordinar:
    return DocumentoParaCoordinar(
        id_documento=id_documento,
        id_paciente="paciente-1",
        tipo_documento=tipo,
        fecha_estudio=fecha,
    )


def test_coordina_estudios_dentro_de_ventana_de_siete_dias() -> None:
    documentos = [
        _documento("ecg-1", TipoDocumento.ECG, date(2024, 1, 1)),
        _documento("lab-1", TipoDocumento.LABORATORIO, date(2024, 1, 8)),
        _documento("eco-1", TipoDocumento.ECOCARDIOGRAMA, date(2024, 1, 6)),
    ]

    resultado = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=True)

    assert len(resultado.episodios_aprobados) == 1
    assert resultado.documentos_en_cuarentena == {}


def test_cuarentena_episodio_con_empate_del_mismo_tipo() -> None:
    documentos = [
        _documento("ecg-1", TipoDocumento.ECG, date(2024, 1, 1)),
        _documento("lab-1", TipoDocumento.LABORATORIO, date(2024, 1, 2)),
        _documento("lab-2", TipoDocumento.LABORATORIO, date(2024, 1, 2)),
        _documento("eco-1", TipoDocumento.ECOCARDIOGRAMA, date(2024, 1, 3)),
    ]

    resultado = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=True)

    assert set(resultado.documentos_en_cuarentena) == {"ecg-1", "lab-1", "lab-2", "eco-1"}
    assert set(resultado.documentos_en_cuarentena.values()) == {MotivoCuarentenaEpisodio.ASOCIACION_AMBIGUA}


def test_episodio_incompleto_espera_cierre_y_luego_va_a_cuarentena() -> None:
    documentos = [
        _documento("ecg-1", TipoDocumento.ECG, date(2024, 1, 1)),
        _documento("lab-1", TipoDocumento.LABORATORIO, date(2024, 1, 2)),
    ]

    antes_del_cierre = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=False)
    despues_del_cierre = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=True)

    assert len(antes_del_cierre.episodios_pendientes) == 1
    assert antes_del_cierre.documentos_en_cuarentena == {}
    assert set(despues_del_cierre.documentos_en_cuarentena) == {"ecg-1", "lab-1"}
    assert set(despues_del_cierre.documentos_en_cuarentena.values()) == {MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES}


def test_documento_a_ocho_dias_abre_otro_episodio_en_lugar_de_forzar_asociacion() -> None:
    documentos = [
        _documento("ecg-1", TipoDocumento.ECG, date(2024, 1, 1)),
        _documento("lab-1", TipoDocumento.LABORATORIO, date(2024, 1, 8)),
        _documento("eco-1", TipoDocumento.ECOCARDIOGRAMA, date(2024, 1, 9)),
    ]

    resultado = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=True)

    assert len(resultado.episodios_aprobados) == 0
    assert set(resultado.documentos_en_cuarentena) == {"ecg-1", "lab-1", "eco-1"}
