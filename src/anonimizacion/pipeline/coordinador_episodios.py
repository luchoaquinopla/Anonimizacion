"""Coordinación durable de estudios por paciente y episodio. La ventana de ±7 días vive
únicamente en `vinculacion.py::vincular_episodios`; este módulo sólo traduce ese resultado a
`EpisodioCoordinado` y decide si el episodio está completo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pseudonimizacion.vinculacion import DocumentoParaVincular, vincular_episodios

# Valor por omisión inyectable de CoordinadorEpisodios.__init__, no una constante fija.
_TIPOS_REQUERIDOS_DEFAULT = frozenset({
    TipoDocumento.ECG,
    TipoDocumento.LABORATORIO,
    TipoDocumento.ECOCARDIOGRAMA,
})


class MotivoCuarentenaEpisodio(str, Enum):
    ESTUDIOS_FALTANTES = "estudios_faltantes"
    ASOCIACION_AMBIGUA = "asociacion_ambigua"


@dataclass(frozen=True)
class DocumentoParaCoordinar:
    id_documento: str
    id_paciente: str
    tipo_documento: TipoDocumento
    fecha_estudio: date


@dataclass(frozen=True)
class EpisodioCoordinado:
    id_episodio: str
    id_paciente: str
    fecha_ancla: date
    documentos: tuple[DocumentoParaCoordinar, ...]


@dataclass(frozen=True)
class ResultadoCoordinacion:
    episodios_aprobados: tuple[EpisodioCoordinado, ...]
    episodios_pendientes: tuple[EpisodioCoordinado, ...]
    documentos_en_cuarentena: dict[str, MotivoCuarentenaEpisodio]


class CoordinadorEpisodios:
    """Agrupa estudios por ancla de siete días y decide sólo al cerrar la corrida."""

    def __init__(
        self, pepper: bytes, tipos_requeridos: frozenset[TipoDocumento] = _TIPOS_REQUERIDOS_DEFAULT
    ) -> None:
        self._pepper = pepper
        self._tipos_requeridos = tipos_requeridos

    def coordinar(
        self,
        documentos: Sequence[DocumentoParaCoordinar],
        *,
        corrida_cerrada: bool,
    ) -> ResultadoCoordinacion:
        aprobados: list[EpisodioCoordinado] = []
        pendientes: list[EpisodioCoordinado] = []
        cuarentena: dict[str, MotivoCuarentenaEpisodio] = {}
        for episodio in self._agrupar_por_ancla(documentos):
            motivo = self._motivo_cuarentena(episodio)
            if motivo is None:
                aprobados.append(episodio)
            elif not corrida_cerrada and motivo is MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES:
                pendientes.append(episodio)
            else:
                cuarentena.update({documento.id_documento: motivo for documento in episodio.documentos})
        return ResultadoCoordinacion(tuple(aprobados), tuple(pendientes), cuarentena)

    def _agrupar_por_ancla(self, documentos: Sequence[DocumentoParaCoordinar]) -> list[EpisodioCoordinado]:
        """Delega el clustering en `vincular_episodios` y lo reexpresa como episodios; no
        reimplementa la ventana."""
        vinculacion = vincular_episodios(
            [
                DocumentoParaVincular(
                    id_documento=documento.id_documento,
                    id_paciente=documento.id_paciente,
                    fecha_estudio=documento.fecha_estudio,
                    tipo_documento=documento.tipo_documento.value,
                )
                for documento in documentos
            ],
            self._pepper,
        )

        agrupados: dict[str, list[DocumentoParaCoordinar]] = {}
        for documento in sorted(
            documentos,
            key=lambda item: (item.fecha_estudio, item.tipo_documento.value, item.id_documento),
        ):
            id_episodio = vinculacion.id_episodio_por_documento[documento.id_documento]
            agrupados.setdefault(id_episodio, []).append(documento)

        return [
            EpisodioCoordinado(
                id_episodio=id_episodio,
                id_paciente=vinculacion.metadata_por_episodio[id_episodio].id_paciente,
                fecha_ancla=vinculacion.metadata_por_episodio[id_episodio].fecha_ancla,
                documentos=tuple(documentos_episodio),
            )
            for id_episodio, documentos_episodio in agrupados.items()
        ]

    def _motivo_cuarentena(self, episodio: EpisodioCoordinado) -> MotivoCuarentenaEpisodio | None:
        tipos = [documento.tipo_documento for documento in episodio.documentos]
        if len(tipos) != len(set(tipos)):
            return MotivoCuarentenaEpisodio.ASOCIACION_AMBIGUA
        # Diferencia de conjuntos: un 4to tipo no requerido no cuarentena, sólo la ausencia de un requerido.
        if self._tipos_requeridos - set(tipos):
            return MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES
        return None


def coordinar_episodios(
    documentos: Sequence[DocumentoParaCoordinar],
    *,
    pepper: bytes,
    corrida_cerrada: bool,
    tipos_requeridos: frozenset[TipoDocumento] = _TIPOS_REQUERIDOS_DEFAULT,
) -> ResultadoCoordinacion:
    return CoordinadorEpisodios(pepper, tipos_requeridos).coordinar(documentos, corrida_cerrada=corrida_cerrada)
