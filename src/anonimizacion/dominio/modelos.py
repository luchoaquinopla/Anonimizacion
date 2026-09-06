"""Modelos tipados del dominio.

`contenido`/`fuentes` de `DocumentoParseado` quedan como `Any` en esta fase:
los tipos concretos (`ContenidoEcg`, `ReferenciaFuente`, etc.) se agregan en
Fase 2 (ingesta) y Fase 4 (parseo) sin romper este contrato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .precision_hora import PrecisionHora
from .referencias import ReferenciaCampo
from .tipos_documento import TipoDocumento


class IdentidadCruda(BaseModel):
    """PII cruda del paciente; SecretStr evita fugas por repr/log/serialización."""

    model_config = ConfigDict(frozen=True)

    nombre: SecretStr
    dni: SecretStr | None = None  # el ECG no trae DNI
    fecha_nac: SecretStr | None = None
    ids_internos: tuple[SecretStr, ...] = Field(default_factory=tuple)  # cuasi-identificadores; tupla: frozen real, no solo de nombre

    def __repr__(self) -> str:  # nunca exponer PII, ni siquiera por accidente
        return "IdentidadCruda(**redactado**)"

    __str__ = __repr__


@dataclass(frozen=True)
class DocumentoParseado:
    """Salida de un `ParseadorDocumento`; la PII vive acá solo en memoria del worker."""

    tipo_documento: TipoDocumento
    version_esquema: int
    identidad: IdentidadCruda
    fecha_estudio: date
    contenido: Any  # ContenidoEcg | ContenidoLaboratorio | ContenidoEco (Fase 4)
    adicionales: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    fuentes: tuple[ReferenciaCampo, ...] = field(default_factory=tuple)
    # Hora del estudio, separada de `fecha_estudio` (spec `momento-del-estudio`).
    # Default `None`/`AUSENTE`: no romper construcciones existentes de otras
    # fases del pipeline que todavía no pasan estos dos campos.
    hora_estudio: time | None = None
    precision_hora: PrecisionHora = PrecisionHora.AUSENTE

    def __post_init__(self) -> None:
        if not isinstance(self.fuentes, tuple) or not all(
            isinstance(fuente, ReferenciaCampo) for fuente in self.fuentes
        ):
            raise TypeError("fuentes debe contener solo ReferenciaCampo")


@dataclass(frozen=True)
class ClavesPaciente:
    """Claves pseudónimas resueltas para un documento — ya no son PII (HMAC)."""

    id_paciente: str | None
    id_alt_paciente: str | None
    version_clave: int


@dataclass(frozen=True)
class RegistroAnonimizado:
    """Registro final de salida: cero PII, listo para Postgres/Parquet."""

    id_paciente: str
    id_episodio: str
    tipo_documento: TipoDocumento
    version_esquema: int
    fecha_estudio: date
    contenido: Any  # datos estructurados sin PII, tipados en Fase 7
    adicionales: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    hora_estudio: time | None = None
    precision_hora: PrecisionHora = PrecisionHora.AUSENTE
    # Identidad estable del documento (spec `escritura-idempotente`); opcional
    # en el dataclass -- las filas legadas y los fixtures sintéticos de otras
    # fases no la traen y no deben romperse. `construir_registro` la exige.
    clave_documento: str | None = None
    # Corrida que produjo este registro (spec `trazabilidad-por-corrida`,
    # Requisito 1). Opcional al final, mismo precedente que `clave_documento`:
    # nace `None` para no romper fixtures ni llamadores existentes que todavía
    # no conocen su corrida. `procesar_lote`/`procesar_grupo` lo propagan
    # (Tramo 2 de `panel-de-operacion`, fuera de alcance de este cambio).
    corrida_id: str | None = None
