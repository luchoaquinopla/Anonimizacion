"""Coordinación durable de estudios por paciente y episodio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pseudonimizacion.claves import generar_id_episodio

_VENTANA_DIAS = 7
_TIPOS_REQUERIDOS = frozenset({
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

    def __init__(self, pepper: bytes) -> None:
        self._pepper = pepper

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
        por_paciente: dict[str, list[DocumentoParaCoordinar]] = {}
        for documento in documentos:
            por_paciente.setdefault(documento.id_paciente, []).append(documento)

        episodios: list[EpisodioCoordinado] = []
        for id_paciente, documentos_paciente in por_paciente.items():
            grupos: list[list[DocumentoParaCoordinar]] = []
            fecha_ancla: date | None = None
            for documento in sorted(documentos_paciente, key=lambda item: (item.fecha_estudio, item.tipo_documento.value, item.id_documento)):
                if fecha_ancla is None or (documento.fecha_estudio - fecha_ancla).days > _VENTANA_DIAS:
                    fecha_ancla = documento.fecha_estudio
                    grupos.append([])
                grupos[-1].append(documento)
            for grupo in grupos:
                ancla = grupo[0].fecha_estudio
                episodios.append(
                    EpisodioCoordinado(
                        id_episodio=generar_id_episodio(self._pepper, id_paciente, ancla),
                        id_paciente=id_paciente,
                        fecha_ancla=ancla,
                        documentos=tuple(grupo),
                    )
                )
        return episodios

    @staticmethod
    def _motivo_cuarentena(episodio: EpisodioCoordinado) -> MotivoCuarentenaEpisodio | None:
        tipos = [documento.tipo_documento for documento in episodio.documentos]
        if len(tipos) != len(set(tipos)):
            return MotivoCuarentenaEpisodio.ASOCIACION_AMBIGUA
        if set(tipos) != _TIPOS_REQUERIDOS:
            return MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES
        return None


def coordinar_episodios(
    documentos: Sequence[DocumentoParaCoordinar],
    *,
    pepper: bytes,
    corrida_cerrada: bool,
) -> ResultadoCoordinacion:
    return CoordinadorEpisodios(pepper).coordinar(documentos, corrida_cerrada=corrida_cerrada)
