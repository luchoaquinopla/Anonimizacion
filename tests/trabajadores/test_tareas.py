"""Tests de `trabajadores/tareas.py` (tasks.md 9.2).

Requisito crítico (spec `batch-processing` + design.md "Sin PII en cola"):
el mensaje de cola transporta SOLO `{id_documento, uri, sha256}`. La firma de
`procesar_documento(id_documento, uri, sha256)` es la prueba por
construcción -- no hay ningún parámetro por el que pueda colarse contenido o
PII. `CELERY_TASK_ALWAYS_EAGER=1` evita necesitar un broker Redis real (ver
`trabajadores/app.py`).
"""

from __future__ import annotations

import os

import pytest

os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"

from anonimizacion.pipeline.ejecutor import ItemLote  # noqa: E402
from anonimizacion.pipeline.resultado import ExitoDocumento  # noqa: E402
from anonimizacion.trabajadores import tareas  # noqa: E402


class _EjecutorFake:
    """Reemplaza `EjecutorPipeline` real -- no requiere spaCy/Postgres."""

    def __init__(self) -> None:
        self.lotes_procesados: list[list[ItemLote]] = []

    def procesar_lote(self, items):
        self.lotes_procesados.append(list(items))
        (item,) = items
        return (
            ExitoDocumento(
                id_documento=item.id_documento,
                tipo_documento=__import__(
                    "anonimizacion.dominio.tipos_documento", fromlist=["TipoDocumento"]
                ).TipoDocumento.LABORATORIO,
                id_paciente="pac-fake",
                id_episodio="ep-fake",
                timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            ),
        )


@pytest.fixture(autouse=True)
def _resetear_ejecutor():
    tareas._fabrica_ejecutor = None
    yield
    tareas._fabrica_ejecutor = None


def test_procesar_documento_sin_configurar_ejecutor_falla_explicito() -> None:
    with pytest.raises(RuntimeError):
        tareas.procesar_documento("doc-1", "s3://bucket/doc-1.pdf", "a" * 64)


def test_procesar_documento_solo_recibe_id_uri_sha256() -> None:
    # Firma de la tarea: exactamente 3 parámetros. Pasar contenido o PII no
    # tiene por dónde colarse -- si algún día alguien agrega un parámetro
    # nuevo, este assert de firma explota primero.
    import inspect

    parametros = list(inspect.signature(tareas.procesar_documento.run).parameters)
    assert parametros == ["id_documento", "uri", "sha256"]


def test_procesar_documento_delega_al_ejecutor_configurado() -> None:
    fake = _EjecutorFake()
    tareas.configurar_ejecutor(lambda: fake)

    resultado = tareas.procesar_documento("doc-1", "s3://bucket/doc-1.pdf", "a" * 64)

    assert len(fake.lotes_procesados) == 1
    (item,) = fake.lotes_procesados[0]
    assert item.id_documento == "doc-1"
    assert item.artefacto.uri == "s3://bucket/doc-1.pdf"
    assert item.artefacto.sha256 == "a" * 64

    assert resultado == {
        "id_documento": "doc-1",
        "tipo_documento": "laboratorio",
        "estado": "exito",
        "timestamp": resultado["timestamp"],
    }


def test_procesar_documento_via_delay_no_requiere_broker_real() -> None:
    fake = _EjecutorFake()
    tareas.configurar_ejecutor(lambda: fake)

    async_result = tareas.procesar_documento.delay("doc-2", "s3://bucket/doc-2.pdf", "b" * 64)

    assert async_result.get()["id_documento"] == "doc-2"
