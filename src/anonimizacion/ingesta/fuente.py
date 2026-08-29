"""Puerto de ingesta y sus adaptadores locales (filesystem).

`FuenteDeArtefactos` es el `Protocol` del puerto (simétrico a
`DestinoEscritura`/`DestinoCuarentena` de `pipeline/ejecutor.py`):
`listar() -> Iterator[ArtefactoCrudo]` y `abrir(artefacto) -> BinaryIO`.
Ningún consumidor del pipeline debe leer bytes de artefactos por otra vía
(spec `ingesta-de-artefactos`).

`FuenteLocal` es el adaptador unificado que reemplazará a `FuenteArtefacto`
e `InventariadorDocumentos` (openspec `puerto-de-ingesta`); por ahora
conviven mientras se completa la migración por fases (ver tasks.md). Agregar
una fuente nueva (un bucket u otro origen) implica una clase nueva que
satisfaga el mismo `Protocol`, no tocar el core del pipeline (mismo
principio que los parsers de Fase 4, ver design.md).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from .artefacto import ArtefactoCrudo, FormatoArtefacto

_EXTENSIONES_SOPORTADAS = {".pdf": FormatoArtefacto.PDF}
_TAMANO_BLOQUE_HUELLA = 1024 * 1024


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
            if not self._esta_dentro_de_raiz(ruta, ruta_raiz):
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
        return any(self._esta_dentro_de_raiz(ruta, raiz) for raiz in self.raices_autorizadas)

    @staticmethod
    def _esta_dentro_de_raiz(ruta: Path, raiz: Path) -> bool:
        try:
            ruta.resolve().relative_to(raiz.resolve())
        except ValueError:
            return False
        return True

    @staticmethod
    def _calcular_huella(ruta: Path) -> str:
        digest = hashlib.sha256()
        with ruta.open("rb") as archivo:
            while bloque := archivo.read(_TAMANO_BLOQUE_HUELLA):
                digest.update(bloque)
        return digest.hexdigest()


@runtime_checkable
class FuenteDeArtefactos(Protocol):
    """Puerto de ingesta: simétrico a `DestinoEscritura`/`DestinoCuarentena`
    (`pipeline/ejecutor.py` L83/L98). El pipeline solo conoce estas dos
    operaciones -- ningún consumidor debe leer bytes de artefactos por otra
    vía (p. ej. `Path(artefacto.uri)` directo, spec `ingesta-de-artefactos`).
    """

    def listar(self) -> Iterator[ArtefactoCrudo]:
        """Descubre artefactos crudos de forma perezosa (spec: sin bloquear
        el inicio del procesamiento hasta terminar de inventariar todo)."""
        ...

    def abrir(self, artefacto: ArtefactoCrudo) -> BinaryIO:
        """Retorna un flujo de bytes legible para el artefacto dado, sin
        exponer una ruta de filesystem al llamador."""
        ...


@runtime_checkable
class RegistroDeHuellas(Protocol):
    """Costura de deduplicación (design.md, Decisión 1): `FuenteLocal` no
    conoce si el registro vive en memoria o respaldado en base -- solo le
    importa si una huella ya fue vista dentro de esta operación de listado.
    """

    def es_nueva(self, sha256: str) -> bool:
        """`True` la primera vez que se ve `sha256`; `False` en repeticiones."""
        ...


@dataclass
class HuellasEnMemoria:
    """Implementación por default de `RegistroDeHuellas`: un `set` de sha256
    hex vistos en esta corrida. Adecuada para tests y corridas chicas; no
    sobrevive a una interrupción del proceso ni es segura entre workers
    concurrentes (para eso, ver la decisión sobre `HuellasDeCorrida` en
    tasks.md -- queda fuera de este cambio por falta de consumidor).
    """

    _vistas: set[str] = field(default_factory=set)

    def es_nueva(self, sha256: str) -> bool:
        if sha256 in self._vistas:
            return False
        self._vistas.add(sha256)
        return True


@dataclass(frozen=True)
class FuenteLocal:
    """Adaptador unificado de ingesta local (`FuenteDeArtefactos`).

    Construcción incremental entre PRs (ver tasks.md, unidades de trabajo):
    esta versión cubre `listar()` con validación ansiosa de raíz autorizada
    y deduplicación delegada a `RegistroDeHuellas`. El tope de tamaño con
    cuarentena (`Protocol SumideroCuarentena` propio) y `abrir()` con
    revalidación de `uri` llegan en la Fase 4-5 (PR2, design.md Decisión 2-3).
    """

    raices: tuple[Path, ...]
    directorio: Path
    huellas: RegistroDeHuellas = field(default_factory=HuellasEnMemoria)

    def __post_init__(self) -> None:
        if not self.raices:
            raise ValueError("debe configurarse al menos una raiz autorizada")

    def listar(self) -> Iterator[ArtefactoCrudo]:
        """Valida raíz y directorio de forma ANSIOSA antes de retornar el
        generador interno (design.md, Decisión 5): un generador "puro" con
        `yield` en su propio cuerpo difiere la validación hasta el primer
        `next()`, lo que rompería la garantía de `PermissionError` inmediato
        ante una raíz no autorizada.
        """
        ruta_raiz = self.directorio.resolve()
        if not ruta_raiz.is_dir():
            raise FileNotFoundError(f"directorio de ingesta inexistente: {self.directorio}")
        if not self._es_ruta_autorizada(ruta_raiz):
            raise PermissionError("la ruta de ingesta no esta autorizada")
        return self._listar_generador(ruta_raiz)

    def _listar_generador(self, ruta_raiz: Path) -> Iterator[ArtefactoCrudo]:
        for ruta in sorted(ruta_raiz.rglob("*")):
            formato = _EXTENSIONES_SOPORTADAS.get(ruta.suffix.lower())
            if formato is None or not ruta.is_file():
                continue
            if not self._esta_dentro_de_raiz(ruta, ruta_raiz):
                continue
            sha256 = self._calcular_huella(ruta)
            if not self.huellas.es_nueva(sha256):
                continue
            yield ArtefactoCrudo(uri=str(ruta), sha256=sha256, formato=formato)

    def _es_ruta_autorizada(self, ruta: Path) -> bool:
        return any(self._esta_dentro_de_raiz(ruta, raiz) for raiz in self.raices)

    @staticmethod
    def _esta_dentro_de_raiz(ruta: Path, raiz: Path) -> bool:
        try:
            ruta.resolve().relative_to(raiz.resolve())
        except ValueError:
            return False
        return True

    @staticmethod
    def _calcular_huella(ruta: Path) -> str:
        digest = hashlib.sha256()
        with ruta.open("rb") as archivo:
            while bloque := archivo.read(_TAMANO_BLOQUE_HUELLA):
                digest.update(bloque)
        return digest.hexdigest()
