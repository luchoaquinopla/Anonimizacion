"""Oráculos de la ventana de ±7 días, escritos a mano sobre `vincular_episodios`.

Antes vivían en `tests/pipeline/test_equivalencia_agrupacion.py`, comparando
`_episodios_del_coordinador(x) == vincular_episodios(x)`. Esa comparación era
tautológica: `coordinador_episodios.py::_agrupar_por_ancla` DELEGA en
`vincular_episodios` (es la única implementación desde el refactor de
`pipeline/coordinador_episodios.py`), así que `f(x) == g(x)` con `f` llamando
a `g` no puede fallar nunca (spec `poder-deteccion-tests`, Requisito 3).

Este archivo conserva los tres oráculos reales que la comparación tautológica
tapaba -- reexpresados directamente sobre `vincular_episodios`, sin el
espejo -- y agrega tres bordes nuevos que no tenían cobertura escrita a mano:
exactamente 7 días ANTES del ancla (simetría del ±), dos anclas del mismo
paciente separadas por meses, y un episodio de un solo documento. Todos
afirman también sobre `metadata_por_episodio[...].fecha_ancla`, que ningún
test anterior verificaba.
"""

from __future__ import annotations

from datetime import date, timedelta

from anonimizacion.pseudonimizacion.vinculacion import DocumentoParaVincular, vincular_episodios

_PEPPER = b"pepper-ventana-de-episodio-nunca-real"
_BASE = date(2024, 1, 10)


def _doc(id_documento: str, id_paciente: str, fecha: date, tipo: str = "laboratorio") -> DocumentoParaVincular:
    return DocumentoParaVincular(id_documento=id_documento, id_paciente=id_paciente, fecha_estudio=fecha, tipo_documento=tipo)


def test_siete_dias_entra_ocho_corta_el_episodio() -> None:
    """7 días entra, 8 abre episodio nuevo (oráculo reexpresado de
    `test_ambas_implementaciones_cortan_el_episodio_en_el_mismo_dia`)."""
    documentos = [
        _doc("d1", "pac-1", _BASE, tipo="laboratorio"),
        _doc("d2", "pac-1", _BASE + timedelta(days=7), tipo="ecg"),
        _doc("d3", "pac-1", _BASE + timedelta(days=8), tipo="ecocardiograma"),
    ]

    resultado = vincular_episodios(documentos, _PEPPER)

    assert resultado.id_episodio_por_documento["d1"] == resultado.id_episodio_por_documento["d2"]
    assert resultado.id_episodio_por_documento["d3"] != resultado.id_episodio_por_documento["d1"]
    ancla_d1 = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["d1"]].fecha_ancla
    ancla_d3 = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["d3"]].fecha_ancla
    assert ancla_d1 == _BASE
    assert ancla_d3 == _BASE + timedelta(days=8)


def test_saltos_encadenados_de_seis_dias_no_se_funden_en_un_episodio_de_doce() -> None:
    """Saltos encadenados de 6 días NO deben fundirse en un episodio de 12
    (oráculo reexpresado de `test_ambas_implementaciones_no_dejan_derivar_la_ventana`)."""
    documentos = [
        _doc("d1", "pac-1", _BASE, tipo="laboratorio"),
        _doc("d2", "pac-1", _BASE + timedelta(days=6), tipo="ecg"),
        _doc("d3", "pac-1", _BASE + timedelta(days=12), tipo="ecocardiograma"),
    ]

    resultado = vincular_episodios(documentos, _PEPPER)

    assert resultado.id_episodio_por_documento["d1"] == resultado.id_episodio_por_documento["d2"]
    assert resultado.id_episodio_por_documento["d3"] != resultado.id_episodio_por_documento["d1"]
    ancla_d1 = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["d1"]].fecha_ancla
    assert ancla_d1 == _BASE  # la ancla no se desplaza a d2 (6/1), evita deriva


def test_pacientes_distintos_nunca_comparten_episodio() -> None:
    """Oráculo reexpresado de `test_ambas_implementaciones_separan_pacientes_distintos`."""
    documentos = [
        _doc("d1", "pac-1", _BASE),
        _doc("d2", "pac-2", _BASE),
    ]

    resultado = vincular_episodios(documentos, _PEPPER)

    assert resultado.id_episodio_por_documento["d1"] != resultado.id_episodio_por_documento["d2"]
    metadata_d1 = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["d1"]]
    metadata_d2 = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["d2"]]
    assert metadata_d1.id_paciente == "pac-1"
    assert metadata_d2.id_paciente == "pac-2"


def test_exactamente_siete_dias_antes_del_ancla_tambien_entra() -> None:
    """Borde nuevo: la ventana es ±7, no sólo hacia adelante. El primer
    documento en orden cronológico fija la ancla -- acá se ordena por fecha
    antes de vincular, así que "siete días antes" se expresa como el
    documento más temprano de los dos."""
    documentos = [
        _doc("temprano", "pac-1", _BASE, tipo="laboratorio"),
        _doc("tardio", "pac-1", _BASE + timedelta(days=7), tipo="ecg"),
    ]

    resultado = vincular_episodios(documentos, _PEPPER)

    assert resultado.id_episodio_por_documento["temprano"] == resultado.id_episodio_por_documento["tardio"]
    ancla = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["temprano"]].fecha_ancla
    assert ancla == _BASE  # la ancla es la fecha del documento más temprano, no la del más tardío


def test_dos_anclas_del_mismo_paciente_separadas_por_meses() -> None:
    """Borde nuevo: mismo paciente, dos episodios muy separados en el tiempo
    -- no debe haber ninguna fuga de agrupación entre ellos ni confusión de
    anclas."""
    ancla_enero = date(2024, 1, 5)
    ancla_julio = date(2024, 7, 5)
    documentos = [
        _doc("d1", "pac-1", ancla_enero, tipo="laboratorio"),
        _doc("d2", "pac-1", ancla_enero + timedelta(days=3), tipo="ecg"),
        _doc("d3", "pac-1", ancla_julio, tipo="laboratorio"),
        _doc("d4", "pac-1", ancla_julio + timedelta(days=2), tipo="ecocardiograma"),
    ]

    resultado = vincular_episodios(documentos, _PEPPER)

    assert resultado.id_episodio_por_documento["d1"] == resultado.id_episodio_por_documento["d2"]
    assert resultado.id_episodio_por_documento["d3"] == resultado.id_episodio_por_documento["d4"]
    assert resultado.id_episodio_por_documento["d1"] != resultado.id_episodio_por_documento["d3"]
    assert len(resultado.metadata_por_episodio) == 2
    ancla_episodio_1 = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["d1"]].fecha_ancla
    ancla_episodio_2 = resultado.metadata_por_episodio[resultado.id_episodio_por_documento["d3"]].fecha_ancla
    assert ancla_episodio_1 == ancla_enero
    assert ancla_episodio_2 == ancla_julio


def test_episodio_de_un_solo_documento() -> None:
    """Borde nuevo: un episodio con un único documento debe tener su propia
    ancla igual a su fecha de estudio, sin agruparse con nada."""
    documentos = [_doc("solo", "pac-1", _BASE)]

    resultado = vincular_episodios(documentos, _PEPPER)

    id_episodio = resultado.id_episodio_por_documento["solo"]
    assert resultado.metadata_por_episodio[id_episodio].fecha_ancla == _BASE
    assert len(resultado.metadata_por_episodio) == 1
