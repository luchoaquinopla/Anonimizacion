"""Puerto de ingesta (`FuenteDeArtefactos`) y su adaptador local de filesystem (`FuenteLocal`).
Ningún consumidor del pipeline debe leer bytes de artefactos por otra vía."""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from ..dominio.errores import CodigoErrorDocumento, ErrorDocumento, EtapaDocumento
from .artefacto import ArtefactoCrudo, FormatoArtefacto

_EXTENSIONES_SOPORTADAS = {".pdf": FormatoArtefacto.PDF}
_TAMANO_BLOQUE_HUELLA = 1024 * 1024
# Provisional: a la espera de medir la distribución real de tamaños de PDF del instituto.
_TOPE_BYTES_PROVISIONAL = 50 * 1024 * 1024
# Sentinel de listar_grupos(): clave de los archivos sin subcarpeta propia bajo la raíz.
# Corpus plano no se trocea por RAM: partir por orden alfabético separaba episodios reales.
_CLAVE_RAIZ = "__raiz__"

_GrupoArtefactos = tuple[ArtefactoCrudo, ...]


@runtime_checkable
class FuenteDeArtefactos(Protocol):
    """Puerto de ingesta: ningún consumidor debe leer bytes de artefactos por otra vía."""

    def listar(self) -> Iterator[ArtefactoCrudo]:
        """Descubre artefactos crudos de forma perezosa."""
        ...

    def listar_grupos(self) -> Iterator[_GrupoArtefactos]:
        """Partición disjunta y exhaustiva de `listar()` en grupos, perezosa."""
        ...

    def abrir(self, artefacto: ArtefactoCrudo) -> BinaryIO:
        """Retorna un flujo de bytes legible sin exponer una ruta de filesystem."""
        ...


@runtime_checkable
class RegistroDeHuellas(Protocol):
    """Costura de deduplicación: sólo importa si una huella ya fue vista en este listado."""

    def es_nueva(self, sha256: str) -> bool:
        """`True` la primera vez que se ve `sha256`; `False` en repeticiones."""
        ...


@runtime_checkable
class SumideroCuarentena(Protocol):
    """`Protocol` propio de `ingesta`, no el de `pipeline/ejecutor.py`: sin depender de `pipeline`."""

    def registrar(self, error: ErrorDocumento) -> None:
        """Aparta un documento a cuarentena con su motivo terminal."""
        ...


@dataclass
class HuellasEnMemoria:
    """`RegistroDeHuellas` en memoria; no sobrevive a una interrupción del proceso."""

    _vistas: set[str] = field(default_factory=set)

    def es_nueva(self, sha256: str) -> bool:
        if sha256 in self._vistas:
            return False
        self._vistas.add(sha256)
        return True


@dataclass
class _CuarentenaNula:
    """Default no-op de `SumideroCuarentena`. Producción MUST inyectar un sumidero real."""

    def registrar(self, error: ErrorDocumento) -> None:
        return None


@dataclass(frozen=True)
class FuenteLocal:
    """Adaptador unificado de ingesta local (`FuenteDeArtefactos`).
    Raíz autorizada como falla dura, cuarentena por sobretamaño sin frenar el lote."""

    raices: tuple[Path, ...]
    directorio: Path
    huellas: RegistroDeHuellas = field(default_factory=HuellasEnMemoria)
    tope_bytes: int = _TOPE_BYTES_PROVISIONAL
    cuarentena: SumideroCuarentena = field(default_factory=_CuarentenaNula)

    def __post_init__(self) -> None:
        if not self.raices:
            raise ValueError("debe configurarse al menos una raiz autorizada")
        if self.tope_bytes <= 0:
            raise ValueError("tope_bytes debe ser positivo")

    def listar(self) -> Iterator[ArtefactoCrudo]:
        """Valida raíz y directorio de forma ansiosa antes de devolver el generador interno."""
        ruta_raiz = self.directorio.resolve()
        if not ruta_raiz.is_dir():
            raise FileNotFoundError(f"directorio de ingesta inexistente: {self.directorio}")
        if not self._es_ruta_autorizada(ruta_raiz):
            raise PermissionError("la ruta de ingesta no esta autorizada")
        return self._listar_generador(ruta_raiz)

    def _listar_generador(self, ruta_raiz: Path) -> Iterator[ArtefactoCrudo]:
        for ruta in sorted(ruta_raiz.rglob("*")):
            if not ruta.is_file() or ruta.name.startswith("."):
                # Directorios y archivos ocultos se omiten en silencio, no son un hallazgo.
                continue
            if not self._esta_dentro_de_raiz(ruta, ruta_raiz):
                # Ruta que resuelve fuera de la raíz autorizada (p.ej. symlink): defensa, se omite.
                continue

            formato = _EXTENSIONES_SOPORTADAS.get(ruta.suffix.lower())
            if formato is None:
                self._apartar_por_formato_no_soportado(ruta)
                continue

            tamano_bytes = ruta.stat().st_size
            if tamano_bytes > self.tope_bytes:
                self._apartar_por_sobretamano(ruta, tamano_bytes)
                continue

            sha256 = self._calcular_huella(ruta)
            if not self.huellas.es_nueva(sha256):
                continue
            yield ArtefactoCrudo(uri=str(ruta), sha256=sha256, formato=formato)

    def listar_grupos(self) -> Iterator[_GrupoArtefactos]:
        """Agrupa `listar()` por subdirectorio inmediato bajo `directorio` (una carpeta por
        paciente); corpus plano cae en un solo grupo `_CLAVE_RAIZ`, sin acotar RAM."""
        ruta_raiz = self.directorio.resolve()
        if not ruta_raiz.is_dir():
            raise FileNotFoundError(f"directorio de ingesta inexistente: {self.directorio}")
        if not self._es_ruta_autorizada(ruta_raiz):
            raise PermissionError("la ruta de ingesta no esta autorizada")
        return self._listar_grupos_generador(ruta_raiz)

    def _listar_grupos_generador(self, ruta_raiz: Path) -> Iterator[_GrupoArtefactos]:
        def _clave(artefacto: ArtefactoCrudo) -> str:
            partes = Path(artefacto.uri).relative_to(ruta_raiz).parts
            return partes[0] if len(partes) > 1 else _CLAVE_RAIZ

        for _clave_grupo, artefactos_del_grupo in itertools.groupby(self._listar_generador(ruta_raiz), key=_clave):
            yield tuple(artefactos_del_grupo)

    def _apartar_por_sobretamano(self, ruta: Path, tamano_bytes: int) -> None:
        # sha256 de la RUTA, no del contenido: el nombre puede llevar PII y el archivo no se lee.
        id_documento = hashlib.sha256(str(ruta).encode("utf-8")).hexdigest()
        self.cuarentena.registrar(
            ErrorDocumento(
                id_documento=id_documento,
                etapa=EtapaDocumento.INGESTA,
                codigo=CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO,
                tamano_bytes=tamano_bytes,
                tope_bytes=self.tope_bytes,
            )
        )

    def _apartar_por_formato_no_soportado(self, ruta: Path) -> None:
        # Mismo criterio que _apartar_por_sobretamano: sha256 de la ruta, contenido sin leer.
        id_documento = hashlib.sha256(str(ruta).encode("utf-8")).hexdigest()
        self.cuarentena.registrar(
            ErrorDocumento(
                id_documento=id_documento,
                etapa=EtapaDocumento.INGESTA,
                codigo=CodigoErrorDocumento.FORMATO_NO_SOPORTADO,
            )
        )

    def abrir(self, artefacto: ArtefactoCrudo) -> BinaryIO:
        """Abre el artefacto revalidando su `uri` y verificando su `sha256`.
        El llamador cierra el flujo devuelto con `with`."""
        ruta = Path(artefacto.uri).resolve()
        if not self._es_ruta_autorizada(ruta):
            raise PermissionError(f"la uri del artefacto no esta autorizada: {artefacto.uri}")

        flujo = ruta.open("rb")
        digest = hashlib.sha256()
        while bloque := flujo.read(_TAMANO_BLOQUE_HUELLA):
            digest.update(bloque)
        sha256_real = digest.hexdigest()
        if sha256_real != artefacto.sha256:
            flujo.close()
            raise ValueError(
                f"el contenido de {artefacto.uri} no coincide con el sha256 esperado "
                f"(esperado={artefacto.sha256}, real={sha256_real})"
            )
        flujo.seek(0)
        return flujo

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
