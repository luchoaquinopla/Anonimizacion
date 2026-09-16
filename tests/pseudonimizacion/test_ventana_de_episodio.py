"""La ventana de ±7 días debe existir UNA sola vez.

`pseudonimizacion/vinculacion.py::vincular_episodios` y
`pipeline/coordinador_episodios.py::CoordinadorEpisodios` implementaban el mismo
clustering por ancla, copiado. Dos copias del mismo algoritmo clínico es una
bomba de tiempo: corregir la deriva de la ventana en una y no en la otra da dos
definiciones distintas de "episodio" según qué camino del pipeline se use.

Estos tests fijan la equivalencia como contrato ANTES de dejar una sola
implementación, y la conservan después.
"""
from __future__ import annotations

from datetime import date, timedelta

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pipeline.coordinador_episodios import (
    DocumentoParaCoordinar,
    coordinar_episodios,
)
from anonimizacion.pseudonimizacion.vinculacion import DocumentoParaVincular, vincular_episodios

_PEPPER = b"pepper-equivalencia-nunca-real"
_BASE = date(2024, 1, 10)


def _pares(documentos: tuple[tuple[str, str, TipoDocumento, date], ...]):
    para_coordinar = [
        DocumentoParaCoordinar(id_doc, id_pac, tipo, fecha) for id_doc, id_pac, tipo, fecha in documentos
    ]
    para_vincular = [
        DocumentoParaVincular(id_doc, id_pac, fecha, tipo.value)
        for id_doc, id_pac, tipo, fecha in documentos
    ]
    return para_coordinar, para_vincular


def _episodios_del_coordinador(para_coordinar) -> dict[str, str]:
    # `corrida_cerrada=False` a proposito: con la corrida cerrada los episodios
    # incompletos van a cuarentena y pierden su `id_episodio`, y lo que se compara
    # aca es la AGRUPACION, no la decision de completitud (que `vincular_episodios`
    # ni siquiera tiene).
    resultado = coordinar_episodios(para_coordinar, pepper=_PEPPER, corrida_cerrada=False)
    asignados: dict[str, str] = {}
    for episodio in resultado.episodios_aprobados + resultado.episodios_pendientes:
        for documento in episodio.documentos:
            asignados[documento.id_documento] = episodio.id_episodio
    return asignados


def test_ambas_implementaciones_agrupan_igual_un_episodio_completo() -> None:
    documentos = (
        ("d1", "pac-1", TipoDocumento.LABORATORIO, _BASE),
        ("d2", "pac-1", TipoDocumento.ECG, _BASE + timedelta(days=1)),
        ("d3", "pac-1", TipoDocumento.ECOCARDIOGRAMA, _BASE + timedelta(days=7)),
    )
    para_coordinar, para_vincular = _pares(documentos)

    assert _episodios_del_coordinador(para_coordinar) == (
        vincular_episodios(para_vincular, _PEPPER).id_episodio_por_documento
    )


def test_ambas_implementaciones_cortan_el_episodio_en_el_mismo_dia() -> None:
    """7 días entra, 8 abre episodio nuevo. El corte debe ser idéntico en las dos."""
    documentos = (
        ("d1", "pac-1", TipoDocumento.LABORATORIO, _BASE),
        ("d2", "pac-1", TipoDocumento.ECG, _BASE + timedelta(days=7)),
        ("d3", "pac-1", TipoDocumento.ECOCARDIOGRAMA, _BASE + timedelta(days=8)),
    )
    para_coordinar, para_vincular = _pares(documentos)

    del_coordinador = _episodios_del_coordinador(para_coordinar)
    de_vinculacion = vincular_episodios(para_vincular, _PEPPER).id_episodio_por_documento

    assert del_coordinador == de_vinculacion
    assert del_coordinador["d1"] == del_coordinador["d2"]
    assert del_coordinador["d3"] != del_coordinador["d1"]


def test_ambas_implementaciones_no_dejan_derivar_la_ventana() -> None:
    """Saltos encadenados de 6 días NO deben fundirse en un episodio de 12."""
    documentos = (
        ("d1", "pac-1", TipoDocumento.LABORATORIO, _BASE),
        ("d2", "pac-1", TipoDocumento.ECG, _BASE + timedelta(days=6)),
        ("d3", "pac-1", TipoDocumento.ECOCARDIOGRAMA, _BASE + timedelta(days=12)),
    )
    para_coordinar, para_vincular = _pares(documentos)

    del_coordinador = _episodios_del_coordinador(para_coordinar)
    assert del_coordinador == vincular_episodios(para_vincular, _PEPPER).id_episodio_por_documento
    assert del_coordinador["d3"] != del_coordinador["d1"]


def test_ambas_implementaciones_separan_pacientes_distintos() -> None:
    documentos = (
        ("d1", "pac-1", TipoDocumento.LABORATORIO, _BASE),
        ("d2", "pac-2", TipoDocumento.LABORATORIO, _BASE),
    )
    para_coordinar, para_vincular = _pares(documentos)

    del_coordinador = _episodios_del_coordinador(para_coordinar)
    assert del_coordinador == vincular_episodios(para_vincular, _PEPPER).id_episodio_por_documento
    assert del_coordinador["d1"] != del_coordinador["d2"]
