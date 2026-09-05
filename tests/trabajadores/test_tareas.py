"""Tests de `trabajadores/tareas.py` (tasks.md 9.2).

Requisito crítico (spec `batch-processing` + design.md "Sin PII en cola"):
el mensaje de cola transporta SOLO referencias `{id_documento, uri, sha256}`,
una por documento del grupo. La unidad de trabajo es el GRUPO y no el documento
(spec `procesamiento-por-grupo`): la validación de episodio necesita ver juntos
todos los estudios del paciente, y un lote de uno nunca contiene los tres tipos
requeridos. `CELERY_TASK_ALWAYS_EAGER=1` evita necesitar un broker Redis real (ver
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
        self.corridas_id_recibidas: list[str | None] = []

    def procesar_lote(self, items, *, corrida_id=None):
        # Un resultado por documento: el lote ya no es de tamano uno.
        self.lotes_procesados.append(list(items))
        self.corridas_id_recibidas.append(corrida_id)
        from datetime import datetime, timezone

        from anonimizacion.dominio.tipos_documento import TipoDocumento

        return tuple(
            ExitoDocumento(
                id_documento=item.id_documento,
                tipo_documento=TipoDocumento.LABORATORIO,
                id_paciente="pac-fake",
                id_episodio="ep-fake",
                timestamp=datetime.now(timezone.utc),
            )
            for item in items
        )


@pytest.fixture(autouse=True)
def _resetear_ejecutor():
    tareas._fabrica_ejecutor = None
    yield
    tareas._fabrica_ejecutor = None


def _referencia(id_documento: str, sha256: str) -> dict[str, str]:
    return {
        "id_documento": id_documento,
        "uri": f"s3://bucket/{id_documento}.pdf",
        "sha256": sha256,
    }


def test_procesar_grupo_sin_configurar_ejecutor_falla_explicito() -> None:
    with pytest.raises(RuntimeError):
        tareas.procesar_grupo("corrida-1", [_referencia("doc-1", "a" * 64)])


def test_procesar_grupo_recibe_exactamente_corrida_id_y_referencias() -> None:
    """Centinela de claves exactas, extendido (design.md Decisión 1): `corrida_id`
    viaja como parámetro HERMANO del lote, nunca como una cuarta clave de la
    referencia por documento -- eso es lo que se verifica más abajo."""
    import inspect

    parametros = list(inspect.signature(tareas.procesar_grupo.run).parameters)
    assert parametros == ["corrida_id", "referencias"]


def test_las_referencias_solo_llevan_id_uri_y_sha256() -> None:
    fake = _EjecutorFake()
    tareas.configurar_ejecutor(lambda: fake)

    tareas.procesar_grupo("corrida-1", [_referencia("doc-1", "a" * 64)])

    (item,) = fake.lotes_procesados[0]
    assert item.id_documento == "doc-1"
    assert item.artefacto.uri == "s3://bucket/doc-1.pdf"
    assert item.artefacto.sha256 == "a" * 64


def test_corrida_id_no_se_cuela_en_la_referencia_por_documento() -> None:
    """`corrida_id` no es una cuarta clave de la referencia: `ItemLote` sigue
    siendo exactamente `{id_documento, artefacto}` (ver
    `test_item_lote_no_gano_ningun_campo_nuevo` en `test_ejecutor.py`), y
    `procesar_grupo` lo propaga aparte, al `procesar_lote` del ejecutor."""
    fake = _EjecutorFake()
    tareas.configurar_ejecutor(lambda: fake)

    tareas.procesar_grupo("corrida-1", [_referencia("doc-1", "a" * 64)])

    (item,) = fake.lotes_procesados[0]
    assert set(item.__dataclass_fields__) == {"id_documento", "artefacto"}
    assert fake.corridas_id_recibidas == ["corrida-1"]


def test_procesar_grupo_manda_todos_los_documentos_en_un_solo_lote() -> None:
    """Lo esencial del cambio: un lote, no N lotes de uno.

    Si el grupo se despachara documento por documento, la coordinación no
    tendría con qué comparar y todo terminaría en cuarentena.
    """
    fake = _EjecutorFake()
    tareas.configurar_ejecutor(lambda: fake)

    tareas.procesar_grupo(
        "corrida-1",
        [
            _referencia("doc-ecg", "a" * 64),
            _referencia("doc-lab", "b" * 64),
            _referencia("doc-eco", "c" * 64),
        ],
    )

    assert len(fake.lotes_procesados) == 1, "el grupo debe viajar como un unico lote"
    assert len(fake.lotes_procesados[0]) == 3


def test_procesar_grupo_vacio_falla_explicito() -> None:
    fake = _EjecutorFake()
    tareas.configurar_ejecutor(lambda: fake)

    with pytest.raises(ValueError):
        tareas.procesar_grupo("corrida-1", [])


def test_procesar_grupo_via_delay_no_requiere_broker_real() -> None:
    fake = _EjecutorFake()
    tareas.configurar_ejecutor(lambda: fake)

    async_result = tareas.procesar_grupo.delay("corrida-1", [_referencia("doc-2", "b" * 64)])

    assert async_result.get()[0]["id_documento"] == "doc-2"

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
