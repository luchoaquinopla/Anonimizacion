"""Vinculación de episodios: clustering por ancla fija, hasta 7 días después, por
`id_paciente`, no encadenado transitivo (un encadenado dejaría "derivar" la ventana: d1-d2
y d2-d3 a 6 días juntarían d1 y d3 a 12 días, clínicamente inaceptable). La ancla nunca se
desplaza dentro de la ventana abierta; `id_episodio` es determinístico y recomputable en batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from anonimizacion.pseudonimizacion.claves import generar_id_episodio

_VENTANA_DIAS = 7


@dataclass(frozen=True)
class DocumentoParaVincular:
    """Vista mínima de un documento ya con `id_paciente` resuelto, para clustering de episodios."""

    id_documento: str
    id_paciente: str
    fecha_estudio: date
    tipo_documento: str


@dataclass(frozen=True)
class MetadataEpisodio:
    """`id_paciente` + `fecha_ancla` de un episodio, lo que `EscritorPostgres.escribir_episodio`
    necesita para persistir la fila `episodio` (ver `sdd/pdf-pii-anonymization/apply-progress`)."""

    id_paciente: str
    fecha_ancla: date


@dataclass(frozen=True)
class ResultadoVinculacion:
    """Resultado de `vincular_episodios`: `id_episodio_por_documento` mapea documento->episodio;
    `metadata_por_episodio` expone `id_paciente`+`fecha_ancla` por episodio único, necesario
    para que `EscritorPostgres.escribir_episodio` corra antes de las filas hijas FK (ver
    `sdd/pdf-pii-anonymization/apply-progress`)."""

    id_episodio_por_documento: dict[str, str]
    metadata_por_episodio: dict[str, MetadataEpisodio]


def vincular_episodios(documentos: list[DocumentoParaVincular], pepper: bytes) -> ResultadoVinculacion:
    """Asigna `id_episodio` a cada `id_documento`, clusterizando por ancla y hasta 7 días
    después, por paciente."""
    por_paciente: dict[str, list[DocumentoParaVincular]] = {}
    for documento in documentos:
        por_paciente.setdefault(documento.id_paciente, []).append(documento)

    id_episodio_por_documento: dict[str, str] = {}
    metadata_por_episodio: dict[str, MetadataEpisodio] = {}
    for id_paciente, documentos_paciente in por_paciente.items():
        ordenados = sorted(
            documentos_paciente,
            key=lambda doc: (doc.fecha_estudio, doc.tipo_documento, doc.id_documento),
        )

        fecha_ancla: date | None = None
        for documento in ordenados:
            if fecha_ancla is None or (documento.fecha_estudio - fecha_ancla).days > _VENTANA_DIAS:
                fecha_ancla = documento.fecha_estudio
            id_episodio = generar_id_episodio(pepper, id_paciente, fecha_ancla)
            id_episodio_por_documento[documento.id_documento] = id_episodio
            # setdefault: sólo el primer documento que abre el episodio fija su metadata.
            metadata_por_episodio.setdefault(
                id_episodio, MetadataEpisodio(id_paciente=id_paciente, fecha_ancla=fecha_ancla)
            )

    return ResultadoVinculacion(
        id_episodio_por_documento=id_episodio_por_documento,
        metadata_por_episodio=metadata_por_episodio,
    )
