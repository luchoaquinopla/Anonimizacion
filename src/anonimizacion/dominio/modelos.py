"""Modelos tipados del dominio.
`contenido`/`fuentes` de `DocumentoParseado` quedan como `Any`: se tipan en fases futuras."""

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
    ids_internos: tuple[SecretStr, ...] = Field(default_factory=tuple)  # cuasi-identificadores

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
    # None/AUSENTE por defecto: no romper construcciones que aún no pasan estos campos.
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
    """Registro final de salida: cero PII, listo para Postgres."""

    id_paciente: str
    id_episodio: str
    tipo_documento: TipoDocumento
    version_esquema: int
    fecha_estudio: date
    contenido: Any  # datos estructurados sin PII, tipados en Fase 7
    adicionales: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    hora_estudio: time | None = None
    precision_hora: PrecisionHora = PrecisionHora.AUSENTE
    # None por compatibilidad con filas legadas y fixtures que no la traen.
    clave_documento: str | None = None
    corrida_id: str | None = None
    # `id_campo` que el PDF traía y el parser no citó; puede repetirse, nunca texto libre.
    campos_no_extraidos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def completo(self) -> bool:
        """Derivada de `campos_no_extraidos`, nunca un segundo estado independiente."""
        return not self.campos_no_extraidos
