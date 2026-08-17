"""Vinculación de episodios: clustering por ancla ±7 días (spec `patient-pseudonymization`).

Ver design.md, decisión "Ventana de ±7 días -- clustering por ancla, no
encadenado". Algoritmo, por `id_paciente`:

1. Ordenar los documentos del paciente por `fecha_estudio` (desempate por
   `(fecha_estudio, tipo_documento, id_documento)` para que el resultado sea
   determinístico incluso con múltiples documentos el mismo día).
2. El primer documento abre un episodio: su fecha es la "ancla".
3. Cada documento siguiente se absorbe al episodio actual si
   `|fecha_estudio - fecha_ancla| <= 7` (7 SÍ entra, 8 NO).
4. El primer documento fuera de rango abre un episodio NUEVO, con su propia
   fecha como nueva ancla -- la ancla nunca se desplaza dentro de la ventana
   ya abierta.
5. `id_episodio = HMAC(pepper, id_paciente + "|" + fecha_ancla)`
   (`claves.generar_id_episodio`): determinístico y recomputable en batch, no
   una mutación incremental de estado -- reprocesar el mismo lote produce
   siempre el mismo resultado (ver `test_es_determinista_y_recomputable_...`).

Por qué NO encadenado transitivo (alternativa rechazada en design.md): unir
episodios cuando CUALQUIER PAR de documentos consecutivos está a ≤7 días deja
que la ventana efectiva "camine" -- si d1 y d2 están a 6 días, y d2 y d3 están
a 6 días, un encadenado transitivo pondría a d1 y d3 en el mismo episodio
aunque estén a 12 días entre sí. Eso es "deriva": con suficientes documentos
intermedios, un episodio podría estirarse indefinidamente, lo cual es
clínicamente inaceptable (un estudio de enero y uno de julio jamás deberían
verse como "el mismo episodio clínico" solo porque hubo estudios cada
semana en el medio). El clustering por ancla fija evita eso: la ventana
siempre se mide desde el primer documento que abrió el episodio.
"""

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
    """`id_paciente` + `fecha_ancla` de un episodio -- lo que
    `salida/destinos/postgres.py::EscritorPostgres.escribir_episodio` necesita
    para persistir la fila `episodio` (fix post-PR9, ver
    `sdd/pdf-pii-anonymization/apply-progress`)."""

    id_paciente: str
    fecha_ancla: date


@dataclass(frozen=True)
class ResultadoVinculacion:
    """Resultado de `vincular_episodios`.

    `id_episodio_por_documento` es el contrato original (Fase 6-9): mapeo
    `id_documento -> id_episodio`, consumido por `pipeline/ejecutor.py` para
    saber qué episodio le corresponde a cada documento resuelto.

    `metadata_por_episodio` es nuevo (fix post-PR9): expone `id_paciente` +
    `fecha_ancla` por episodio ÚNICO (una entrada por episodio, no por
    documento) -- sin esto, `pipeline/ejecutor.py` no tenía forma de saber
    qué `fecha_ancla` pasarle a `EscritorPostgres.escribir_episodio` antes de
    emitir las filas hijas (`resultado_laboratorio`/`medicion_ecg`/
    `medicion_eco`/`texto_seccion_eco`), que son FK contra `episodio` --
    ver docstring del módulo, apartado "por qué pasa" en apply-progress.
    """

    id_episodio_por_documento: dict[str, str]
    metadata_por_episodio: dict[str, MetadataEpisodio]


def vincular_episodios(documentos: list[DocumentoParaVincular], pepper: bytes) -> ResultadoVinculacion:
    """Asigna `id_episodio` a cada `id_documento`, clusterizando por ancla ±7 días por paciente."""
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
            # `setdefault`: el primer documento que abre el episodio fija su
            # metadata; documentos siguientes absorbidos al mismo episodio no
            # deben pisarla (misma `fecha_ancla` de todos modos, por construcción).
            metadata_por_episodio.setdefault(
                id_episodio, MetadataEpisodio(id_paciente=id_paciente, fecha_ancla=fecha_ancla)
            )

    return ResultadoVinculacion(
        id_episodio_por_documento=id_episodio_por_documento,
        metadata_por_episodio=metadata_por_episodio,
    )
