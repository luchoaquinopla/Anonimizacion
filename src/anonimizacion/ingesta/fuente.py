"""`FuenteArtefacto`: adaptador de ingesta que lista artefactos desde un filesystem local.

Puerto/adaptador (hexagonal): el pipeline solo conoce el método `listar()`; el
origen concreto (filesystem hoy, un bucket u otra fuente mañana) queda
aislado acá. Agregar una fuente nueva implica una clase nueva con el mismo
método, no tocar el core del pipeline (mismo principio que los parsers de
Fase 4, ver design.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .artefacto import ArtefactoCrudo, FormatoArtefacto

_EXTENSIONES_SOPORTADAS = {".pdf": FormatoArtefacto.PDF}


@dataclass(frozen=True)
class FuenteArtefacto:
    """Lista `ArtefactoCrudo` a partir de los archivos de un directorio local."""

    directorio: Path

    def listar(self) -> list[ArtefactoCrudo]:
        if not self.directorio.is_dir():
            raise FileNotFoundError(f"directorio de ingesta inexistente: {self.directorio}")

        artefactos = []
        for ruta in sorted(self.directorio.iterdir()):
            formato = _EXTENSIONES_SOPORTADAS.get(ruta.suffix.lower())
            if formato is None or not ruta.is_file():
                continue
            sha256 = hashlib.sha256(ruta.read_bytes()).hexdigest()
            artefactos.append(ArtefactoCrudo(uri=str(ruta), sha256=sha256, formato=formato))
        return artefactos
