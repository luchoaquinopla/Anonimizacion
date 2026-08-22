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

_TAMANO_BLOQUE_HUELLA = 1024 * 1024


@dataclass(frozen=True)
class InventariadorDocumentos:
    """Inventaría PDFs de una raíz autorizada sin repetir el mismo contenido."""

    raices_autorizadas: tuple[Path, ...]
    tamano_maximo_bytes: int

    def __post_init__(self) -> None:
        if not self.raices_autorizadas:
            raise ValueError("debe configurarse al menos una raiz autorizada")
        if self.tamano_maximo_bytes <= 0:
            raise ValueError("tamano_maximo_bytes debe ser positivo")

    def inventariar(self, directorio: Path) -> list[ArtefactoCrudo]:
        ruta_raiz = directorio.resolve()
        if not ruta_raiz.is_dir():
            raise FileNotFoundError("directorio de ingesta inexistente")
        if not self._es_ruta_autorizada(ruta_raiz):
            raise PermissionError("la ruta de ingesta no esta autorizada")

        artefactos: list[ArtefactoCrudo] = []
        huellas_vistas: set[str] = set()
        for ruta in sorted(ruta_raiz.rglob("*")):
            formato = _EXTENSIONES_SOPORTADAS.get(ruta.suffix.lower())
            if formato is None or not ruta.is_file():
                continue
            if ruta.stat().st_size > self.tamano_maximo_bytes:
                raise ValueError("archivo PDF supera el tamano maximo permitido")

            sha256 = self._calcular_huella(ruta)
            if sha256 in huellas_vistas:
                continue
            huellas_vistas.add(sha256)
            artefactos.append(ArtefactoCrudo(uri=str(ruta), sha256=sha256, formato=formato))
        return artefactos

    def _es_ruta_autorizada(self, ruta: Path) -> bool:
        for raiz_autorizada in self.raices_autorizadas:
            try:
                ruta.relative_to(raiz_autorizada.resolve())
            except ValueError:
                continue
            return True
        return False

    @staticmethod
    def _calcular_huella(ruta: Path) -> str:
        digest = hashlib.sha256()
        with ruta.open("rb") as archivo:
            while bloque := archivo.read(_TAMANO_BLOQUE_HUELLA):
                digest.update(bloque)
        return digest.hexdigest()
