"""Puerto de ingesta y su adaptador local (filesystem).

`FuenteDeArtefactos` es el `Protocol` del puerto (simétrico a
`DestinoEscritura`/`DestinoCuarentena` de `pipeline/ejecutor.py`):
`listar() -> Iterator[ArtefactoCrudo]` y `abrir(artefacto) -> BinaryIO`.
Ningún consumidor del pipeline debe leer bytes de artefactos por otra vía
(spec `ingesta-de-artefactos`).

`FuenteLocal` es el adaptador unificado (openspec `puerto-de-ingesta`) que
reemplaza a los antiguos `FuenteArtefacto`/`InventariadorDocumentos`. Agregar
una fuente nueva (un bucket u otro origen) implica una clase nueva que
satisfaga el mismo `Protocol`, no tocar el core del pipeline (mismo
principio que los parsers de Fase 4, ver design.md).

`FuenteLocal` no importa `pipeline`: declara su propio `Protocol
SumideroCuarentena`, satisfecho por tipado estructural por
`EscritorCuarentena` (`salida/cuarentena.py`) sin acoplamiento de módulos.
"""

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
# Provisional (design.md, "Preguntas abiertas"): a la espera de medir la
# distribución real de tamaños de PDF del instituto. Ajustar acá cuando esa
# medición exista -- es lo único que hay que tocar.
_TOPE_BYTES_PROVISIONAL = 50 * 1024 * 1024
# Sentinel de `listar_grupos()`: clave compartida por los archivos que están
# directamente bajo la raíz, sin subcarpeta propia (corpus plano o sueltos
# mezclados con carpetas -- ver docstring de `listar_grupos`).
_CLAVE_RAIZ = "__raiz__"


@dataclass(frozen=True)
class GrupoArtefactos:
    """Partición de `listar()` en unidades de trabajo (spec
    `procesamiento-por-grupo`, openspec `paralelismo-de-procesamiento`).

    `id_grupo` es un HASH, nunca la ruta ni el nombre de la subcarpeta: el
    nombre de carpeta puede llevar PII (nombre del paciente), igual que la
    `uri` de un `ArtefactoCrudo` apartado por sobretamaño
    (`_apartar_por_sobretamano`, más abajo).
    """

    id_grupo: str
    artefactos: tuple[ArtefactoCrudo, ...]


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

    def listar_grupos(self) -> Iterator[GrupoArtefactos]:
        """Partición disjunta y exhaustiva de `listar()` en grupos -- el
        criterio de agrupamiento lo define el adaptador (para `FuenteLocal`,
        el subdirectorio inmediato). Perezoso igual que `listar()`: un
        adaptador conforme NO debe materializar la partición completa antes
        de entregar el primer grupo."""
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


@runtime_checkable
class SumideroCuarentena(Protocol):
    """`Protocol` propio de `ingesta`, NO el de `pipeline/ejecutor.py`
    (design.md, Decisión 3): este módulo no debe depender de `pipeline`.
    `EscritorCuarentena` (`salida/cuarentena.py`) lo satisface por tipado
    estructural sin que exista un import cruzado.
    """

    def registrar(self, error: ErrorDocumento) -> None:
        """Aparta un documento a cuarentena con su motivo terminal."""
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


@dataclass
class _CuarentenaNula:
    """Default no-op de `SumideroCuarentena`: descarta los errores.

    Existe solo para que `FuenteLocal` sea instanciable en tests que no
    ejercitan el camino de sobretamaño sin forzar a cada test a construir un
    sumidero. Producción MUST inyectar un sumidero real (p. ej.
    `EscritorCuarentena`) -- descartar cuarentenas en silencio en producción
    perdería documentos sin dejar rastro.
    """

    def registrar(self, error: ErrorDocumento) -> None:
        return None


@dataclass(frozen=True)
class FuenteLocal:
    """Adaptador unificado de ingesta local (`FuenteDeArtefactos`).

    Cubre las cinco garantías de la spec `ingesta-de-artefactos`: pereza
    (`listar()` valida ansiosamente y devuelve un generador), raíz autorizada
    como falla dura, cuarentena por sobretamaño sin frenar el lote,
    deduplicación por contenido delegada, y hasheo por bloques. `abrir()`
    revalida la `uri` (puede venir de una cola envenenada) y verifica que el
    sha256 declarado coincida con el contenido real antes de entregar el
    flujo (design.md, Decisión 2).
    """

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
            if not ruta.is_file() or ruta.name.startswith("."):
                # Directorios y archivos ocultos no son un hallazgo del
                # corpus: no se leen ni se apartan, se omiten en silencio
                # (mismo criterio de siempre, ver test correspondiente).
                continue
            if not self._esta_dentro_de_raiz(ruta, ruta_raiz):
                # Enlace simbólico (u otra ruta) que resuelve fuera de la
                # raíz autorizada: defensa de seguridad, no un hallazgo del
                # corpus -- se omite en silencio, distinto del caso de abajo.
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

    def listar_grupos(self) -> Iterator[GrupoArtefactos]:
        """Agrupa `listar()` por subdirectorio inmediato bajo `directorio`.

        Criterio del instituto (reunión 2026-08-21, citada en el proposal
        `paralelismo-de-procesamiento`): una carpeta por paciente, con los
        estudios del episodio adentro. **Todavía no llegó ninguna muestra
        real** -- este criterio es la mejor hipótesis verificable hoy, no un
        hecho confirmado.

        Perezoso, no ansioso: reutiliza `_listar_generador`, que ya produce
        artefactos ordenados por ruta completa (`sorted(rglob(...))`). Ese
        orden hace que todo el subárbol de una misma subcarpeta quede
        contiguo en el flujo -- el separador de path ('/', 0x2F en ASCII)
        ordena antes que cualquier caracter de nombre de archivo o carpeta,
        así que dos subcarpetas nunca intercalan sus artefactos entre sí.
        Eso permite agrupar con `itertools.groupby` sin materializar la
        partición completa: cada grupo se cierra y se entrega apenas cambia
        la clave, nunca se retiene más de un grupo en memoria a la vez (es
        exactamente la propiedad que evita que `procesar_lote` acumule en
        RAM los resueltos de la corrida entera).

        Corpus plano (honesto sobre la incertidumbre real -- ver proposal.md
        "Antes de leer"): si no hay subcarpetas, todos los archivos sueltos
        bajo `directorio` comparten la clave sentinel `_CLAVE_RAIZ` y, al no
        haber ninguna subcarpeta que los separe, forman un único grupo
        contiguo. El paralelismo del tramo 3 rendiría cero en ese caso -- es
        el comportamiento esperado, no un bug de esta función.

        Advertencia documentada, no maquillada: en un corpus MIXTO -- algunas
        subcarpetas y ADEMÁS archivos sueltos intercalados alfabéticamente
        entre ellas -- los archivos sueltos pueden partirse en más de un
        grupo con la misma clave sentinel, si una subcarpeta los separa en el
        orden alfabético. La partición sigue siendo disjunta y exhaustiva
        (ningún archivo se pierde ni se cuenta dos veces: cada `ArtefactoCrudo`
        que `listar()` produce cae en EXACTAMENTE un grupo), sólo dejan de
        terminar todos con el mismo `id_grupo`. El corpus real descripto por
        el instituto no tiene esa mezcla (o todo tiene subcarpetas, o nada
        las tiene); resolver el caso mixto exigiría des-perezar la función
        (acumular todos los archivos sueltos hasta agotar el listado), y no
        hay hoy ningún corpus real que lo requiera.
        """
        ruta_raiz = self.directorio.resolve()
        if not ruta_raiz.is_dir():
            raise FileNotFoundError(f"directorio de ingesta inexistente: {self.directorio}")
        if not self._es_ruta_autorizada(ruta_raiz):
            raise PermissionError("la ruta de ingesta no esta autorizada")
        return self._listar_grupos_generador(ruta_raiz)

    def _listar_grupos_generador(self, ruta_raiz: Path) -> Iterator[GrupoArtefactos]:
        def _clave(artefacto: ArtefactoCrudo) -> str:
            partes = Path(artefacto.uri).relative_to(ruta_raiz).parts
            return partes[0] if len(partes) > 1 else _CLAVE_RAIZ

        for clave, artefactos_del_grupo in itertools.groupby(self._listar_generador(ruta_raiz), key=_clave):
            artefactos = tuple(artefactos_del_grupo)
            # Hash de la clave de agrupamiento (subcarpeta o sentinel de raíz)
            # junto con la `uri` del primer artefacto: nunca la ruta cruda
            # (design.md `procesamiento-por-grupo`, Decisión 2 -- el nombre de
            # carpeta puede ser PII), y distingue dos instancias de grupo que
            # compartieran la misma clave (ver advertencia del corpus mixto).
            id_grupo = hashlib.sha256(f"{clave}:{artefactos[0].uri}".encode("utf-8")).hexdigest()
            yield GrupoArtefactos(id_grupo=id_grupo, artefactos=artefactos)

    def _apartar_por_sobretamano(self, ruta: Path, tamano_bytes: int) -> None:
        # `id_documento` es el sha256 de la RUTA, no del contenido: el nombre
        # de archivo puede llevar PII (nombre del paciente) y no se propaga;
        # el contenido no se lee -- es exactamente la lectura que evitamos
        # (design.md, Decisión 3).
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
        # Mismo criterio que `_apartar_por_sobretamano`: `id_documento` es el
        # sha256 de la RUTA, no del contenido. El nombre de archivo puede
        # llevar PII y no se propaga; el contenido tampoco se lee -- no hay
        # ningún parser que sepa qué hacer con un formato no soportado, así
        # que leerlo no aportaría nada y sería trabajo (y riesgo) de más.
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

        Ciclo de vida (design.md, Decisión 2): retorna un `BinaryIO` fresco e
        independiente; el LLAMADOR lo cierra con `with` -- un objeto de
        archivo ya es context manager, no hace falta un envoltorio.

        La `uri` llega desde la cola de Celery, potencialmente manipulada:
        revalidarla acá (no solo en `listar()`) cierra un agujero real, no
        una formalidad. La verificación de sha256 se hace sobre los mismos
        bytes que se le van a entregar a PyMuPDF, que de todos modos necesita
        el buffer completo -- el segundo pase de hash es despreciable frente
        al parseo.
        """
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
