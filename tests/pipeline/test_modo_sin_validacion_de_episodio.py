"""Deja por escrito que el modo por documento NO valida completitud de episodio.

Esto no es una prueba de una funcionalidad: es una prueba de una LIMITACIÓN
conocida, para que deje de ser silenciosa.

`EjecutorPipeline` recibe `coordinar_episodios=None` por defecto y, en ese modo,
`_coordinar_resueltos` devuelve una lista de fallos vacía: ningún documento se
aparta por episodio incompleto o por asociación ambigua. La tarea Celery
`procesar_documento` arma `procesar_lote([item])` -- un lote de UN documento --
así que ese es el modo en que corre el worker hoy.

Y no puede ser de otra forma con ese diseño: un lote de un documento nunca tiene
los tres tipos requeridos, de modo que activar el coordinador ahí mandaría el
100 % de los documentos a cuarentena. La validación de episodio necesita la
corrida completa, y esa coordinación al cierre todavía no existe en producción.

Consecuencia que hay que tener presente al leer los ensayos de carga: el corpus
sintético SÍ inyecta el coordinador (`tests/fixtures/corpus_piloto.py`) porque
procesa todo el corpus como un único lote. Sus conteos de cuarentena por
episodio incompleto describen el modo por lote, no el modo por documento del
worker.
"""
from __future__ import annotations

from datetime import date, timedelta

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pipeline.coordinador_episodios import (
    DocumentoParaCoordinar,
    MotivoCuarentenaEpisodio,
    coordinar_episodios,
)

_PEPPER = b"pepper-limitacion-nunca-real"
_BASE = date(2024, 1, 10)


def test_un_lote_de_un_documento_no_puede_formar_un_episodio_completo() -> None:
    """Por eso el worker por documento no puede activar el coordinador tal cual está."""
    resultado = coordinar_episodios(
        [DocumentoParaCoordinar("doc-1", "pac-1", TipoDocumento.LABORATORIO, _BASE)],
        pepper=_PEPPER,
        corrida_cerrada=True,
    )

    assert resultado.episodios_aprobados == ()
    assert resultado.documentos_en_cuarentena == {
        "doc-1": MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES
    }


def test_el_mismo_lote_con_los_tres_tipos_si_aprueba() -> None:
    """La diferencia no es el documento: es el tamaño del lote que se coordina."""
    documentos = [
        DocumentoParaCoordinar("d1", "pac-1", TipoDocumento.LABORATORIO, _BASE),
        DocumentoParaCoordinar("d2", "pac-1", TipoDocumento.ECG, _BASE + timedelta(days=1)),
        DocumentoParaCoordinar("d3", "pac-1", TipoDocumento.ECOCARDIOGRAMA, _BASE + timedelta(days=2)),
    ]

    resultado = coordinar_episodios(documentos, pepper=_PEPPER, corrida_cerrada=True)

    assert len(resultado.episodios_aprobados) == 1
    assert resultado.documentos_en_cuarentena == {}


def test_el_ejecutor_sin_coordinador_no_aparta_ningun_documento() -> None:
    """El default `coordinar_episodios=None` desactiva la validación de episodio.

    Si algún día se le pone un default distinto de `None`, este test falla y
    obliga a revisar el modo por documento antes de cambiarlo.
    """
    import inspect

    from anonimizacion.pipeline.ejecutor import EjecutorPipeline

    firma = inspect.signature(EjecutorPipeline.__init__)
    assert firma.parameters["coordinar_episodios"].default is None, (
        "el default cambió: revisar que el worker por documento no quede "
        "mandando el 100 % de los documentos a cuarentena"
    )
