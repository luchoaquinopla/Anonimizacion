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

class _ExtractorFake:
    def __init__(self) -> None:
        self.minimas = 0

    def extraer_minimo(self, artefacto) -> None:
        self.minimas += 1


class _RepositorioFake:
    def __init__(self) -> None:
        from anonimizacion.dominio.corridas import DocumentoCorrida

        self.version_persistida = 0
        self.documento = DocumentoCorrida.inventariado(
            corrida_id="corrida-1", huella_contenido="c" * 64, ruta_autorizada="entrada.pdf"
        )

    def documentos_para_reanudar(self, corrida_id):
        return [self.documento]

    def actualizar_documento(self, documento, *, version_esperada):
        if self.version_persistida != version_esperada:
            return False
        self.documento = documento
        return True


def test_extraccion_minima_reanuda_sin_ejecutar_ni_duplicar_documento() -> None:
    extractor = _ExtractorFake()
    repositorio = _RepositorioFake()
    tareas.configurar_extractor(lambda: extractor, repositorio)

    primero = tareas.procesar_extraccion_minima("corrida-1", "entrada.pdf", "c" * 64)
    segundo = tareas.procesar_extraccion_minima("corrida-1", "entrada.pdf", "c" * 64)

    assert primero["estado"] == "extraido_minimo"
    assert segundo["estado"] == "extraido_minimo"
    assert extractor.minimas == 1


def test_extraccion_completa_persiste_sin_publicar() -> None:
    from anonimizacion.dominio.estados_corrida import EstadoDocumentoCorrida

    class ExtractorCompleto(_ExtractorFake):
        def __init__(self) -> None:
            super().__init__()
            self.completas = 0

        def extraer_completo(self, artefacto) -> None:
            self.completas += 1

    extractor = ExtractorCompleto()
    repositorio = _RepositorioFake()
    for estado in (
        EstadoDocumentoCorrida.CLASIFICADO,
        EstadoDocumentoCorrida.EXTRAIDO_MINIMO,
        EstadoDocumentoCorrida.ASOCIADO,
    ):
        repositorio.documento.avanzar_a(estado)
    repositorio.version_persistida = repositorio.documento.version
    tareas.configurar_extractor(lambda: extractor, repositorio)

    resultado = tareas.procesar_extraccion_completa("corrida-1", "entrada.pdf", "c" * 64)

    assert resultado == {"estado": "extraido_completo"}
    assert extractor.completas == 1
