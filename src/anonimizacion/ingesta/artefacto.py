"""`ArtefactoCrudo`: representación de un archivo fuente antes de parsear.
Sin PII (solo metadatos de integridad/localización): `dataclass` simple, no `BaseModel`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class FormatoArtefacto(str, Enum):
    """Formatos de archivo soportados como entrada del pipeline."""

    PDF = "pdf"


@dataclass(frozen=True)
class ArtefactoCrudo:
    """Artefacto sin procesar: uri (localización), sha256 (integridad) y formato.
    `sha256` valida formato (64 hex minúsculas) para detectar errores de cómputo temprano."""

    uri: str
    sha256: str
    formato: FormatoArtefacto

    def __post_init__(self) -> None:
        if not self.uri:
            raise ValueError("uri no puede estar vacía")
        if not _SHA256_HEX.match(self.sha256):
            raise ValueError("sha256 debe ser 64 dígitos hexadecimales en minúscula")
