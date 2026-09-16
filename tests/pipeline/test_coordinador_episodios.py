from __future__ import annotations

from datetime import date
from enum import Enum

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pipeline.coordinador_episodios import (
    CoordinadorEpisodios,
    DocumentoParaCoordinar,
    MotivoCuarentenaEpisodio,
    coordinar_episodios,
)

_PEPPER = b"pepper-test-coordinador"


# 4to tipo de documento simulado (Requisito 4, extensibilidad-tipo-documento):
# `DocumentoParaCoordinar.tipo_documento` no valida en runtime que sea un
# miembro de `TipoDocumento` -- alcanza un `str, Enum` propio con el mismo
# mixin, sin monkeypatchear el enum real (que rompería los `is` que usa el
# resto del pipeline contra los 3 tipos reales).
class _TipoDocumentoDePrueba(str, Enum):
    RESONANCIA_MAGNETICA = "resonancia_magnetica"


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


def test_episodio_con_los_3_tipos_requeridos_mas_un_4to_tipo_no_cae_en_estudios_faltantes() -> None:
    """Requisito 2, Escenario 1. RED contra el código de hoy
    (`set(tipos) != _TIPOS_REQUERIDOS`, igualdad exacta): un episodio con los
    3 tipos requeridos MÁS un 4to tipo no requerido tiene `set(tipos)` de 4
    elementos, nunca igual al frozenset de 3 -- cae en `ESTUDIOS_FALTANTES`
    aunque esté completo. Con la diferencia de conjuntos
    (`tipos_requeridos - set(tipos)`) el 4to tipo sobra sin afectar el
    resultado: la resta es vacía apenas los 3 requeridos están presentes.

    Única divergencia semántica declarada de toda la cadena (design.md D1,
    acta de una línea, tasks.md 1.7): antes de este cambio este mismo
    episodio quedaba en cuarentena; a partir de acá queda aprobado."""
    documentos = [
        _documento("ecg-1", TipoDocumento.ECG, date(2024, 1, 1)),
        _documento("lab-1", TipoDocumento.LABORATORIO, date(2024, 1, 2)),
        _documento("eco-1", TipoDocumento.ECOCARDIOGRAMA, date(2024, 1, 3)),
        _documento("rm-1", _TipoDocumentoDePrueba.RESONANCIA_MAGNETICA, date(2024, 1, 3)),
    ]

    resultado = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=True)

    assert len(resultado.episodios_aprobados) == 1
    assert resultado.documentos_en_cuarentena == {}


def test_episodio_al_que_le_falta_un_requerido_sigue_en_estudios_faltantes_con_4to_tipo_presente() -> None:
    """Requisito 2, Escenario 2: la diferencia de conjuntos sigue detectando
    lo que realmente falta -- que sobre un tipo no requerido no tapa que
    falte uno requerido."""
    documentos = [
        _documento("ecg-1", TipoDocumento.ECG, date(2024, 1, 1)),
        _documento("rm-1", _TipoDocumentoDePrueba.RESONANCIA_MAGNETICA, date(2024, 1, 1)),
    ]

    resultado = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=True)

    assert len(resultado.episodios_aprobados) == 0
    assert set(resultado.documentos_en_cuarentena) == {"ecg-1", "rm-1"}
    assert set(resultado.documentos_en_cuarentena.values()) == {MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES}


def test_coordinador_episodios_recibe_tipos_requeridos_inyectado_en_init() -> None:
    """Requisito 2: `tipos_requeridos` es parámetro de `__init__`, no
    constante de módulo -- un coordinador con un conjunto requerido distinto
    (un solo tipo) aprueba un episodio que el coordinador por omisión
    apartaría por `ESTUDIOS_FALTANTES`."""
    coordinador = CoordinadorEpisodios(_PEPPER, tipos_requeridos=frozenset({TipoDocumento.ECG}))
    documentos = [_documento("ecg-1", TipoDocumento.ECG, date(2024, 1, 1))]

    resultado = coordinador.coordinar(documentos, corrida_cerrada=True)

    assert len(resultado.episodios_aprobados) == 1
    assert resultado.documentos_en_cuarentena == {}
