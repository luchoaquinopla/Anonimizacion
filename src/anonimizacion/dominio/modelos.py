"""Modelos tipados del dominio.

`contenido`/`fuentes` de `DocumentoParseado` quedan como `Any` en esta fase:
los tipos concretos (`ContenidoEcg`, `ReferenciaFuente`, etc.) se agregan en
Fase 2 (ingesta) y Fase 4 (parseo) sin romper este contrato.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .tipos_documento import TipoDocumento

if TYPE_CHECKING:
    from anonimizacion.reconciliacion.base import ReferenciaCampo


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

    def __post_init__(self) -> None:
        from anonimizacion.reconciliacion.base import ReferenciaCampo

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
