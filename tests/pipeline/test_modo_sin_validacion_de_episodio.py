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


def test_el_nucleo_conserva_el_default_sin_coordinador() -> None:
    """El default sigue siendo `None`, y eso es correcto.

    "Un lote no es necesariamente un episodio" es una verdad del núcleo. "En
    producción el lote ES un grupo" es política de despliegue y vive en la raíz
    de composición, no acá. Por eso el default no cambia: lo que cambió es que
    la fábrica de producción ahora sí inyecta el coordinador (ver el centinela
    inverso, abajo).
    """
    import inspect

    from anonimizacion.pipeline.ejecutor import EjecutorPipeline

    firma = inspect.signature(EjecutorPipeline.__init__)
    assert firma.parameters["coordinar_episodios"].default is None


def test_la_fabrica_de_produccion_si_inyecta_el_coordinador() -> None:
    """Centinela inverso: ningún camino de producción debe quedar sin validar.

    Si alguien quita esta inyección, la validación de episodio desaparece en
    silencio de producción -- que es exactamente el estado que este cambio vino
    a corregir.
    """
    import inspect

    from anonimizacion.trabajadores import tareas

    fuente = inspect.getsource(tareas.construir_fabrica_ejecutor)
    assert "coordinar_episodios" in fuente, (
        "la raiz de composicion de produccion dejo de inyectar el coordinador: "
        "sin el, un grupo incompleto se publica sin aviso"
    )
