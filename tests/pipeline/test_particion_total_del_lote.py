"""Centinela de la partición total del lote (design.md, Decisión 6).

`procesar_lote` **MUST** devolver exactamente un resultado por ítem de
entrada. Hoy eso es cierto por accidente: `_coordinar_resueltos` llama al
coordinador con `corrida_cerrada=True` fijo, y con `True` el coordinador real
nunca puebla `episodios_pendientes` (ver `coordinador_episodios.py:80`) --
así que `resueltos_aprobados ∪ fallos` cubre hoy todos los resueltos, pero
solo porque el coordinador real se comporta así. Si se inyecta un
coordinador que sí deja pendientes (el caso que este archivo fuerza a mano),
esos documentos desaparecen del valor de retorno en silencio.

La elección del diseño (Decisión 6, tabla de alternativas) es fallar
ruidoso ante esa situación -- no es un fallo del documento, es una
configuración cuya contabilidad no existe -- en vez de mandarlo a cuarentena
(mentiría sobre el desenlace) o inventar un estado nuevo (media reanudación
fuera de alcance).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.pipeline.coordinador_episodios import (
    DocumentoParaCoordinar,
    EpisodioCoordinado,
    MotivoCuarentenaEpisodio,
    ResultadoCoordinacion,
)
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pseudonimizacion.vinculacion import MetadataEpisodio, ResultadoVinculacion

PEPPER = b"pepper-particion-total-del-lote"


def _artefacto(nombre: str) -> ArtefactoCrudo:
    return ArtefactoCrudo(uri=f"/fake/{nombre}.pdf", sha256="a" * 64, formato=FormatoArtefacto.PDF)


def _documento() -> DocumentoParseado:
    return DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=None,
        fecha_estudio=date(2026, 1, 10),
        contenido=object(),
        adicionales={},
        fuentes=(),
    )


@dataclass
class _EscritorFake:
    escritos: list

    def escribir_episodio(self, *, id_episodio, id_paciente, fecha_ancla) -> None:
        return None

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        self.escritos.append(registro)


@dataclass
class _CuarentenaFake:
    registrados: list

    def registrar(self, error) -> None:
        self.registrados.append(error)


def _episodio_de(documento: DocumentoParaCoordinar) -> EpisodioCoordinado:
    return EpisodioCoordinado(
        id_episodio=f"episodio-{documento.id_paciente}",
        id_paciente=documento.id_paciente,
        fecha_ancla=documento.fecha_estudio,
        documentos=(documento,),
    )


def _construir_ejecutor(*, coordinar_episodios) -> tuple[EjecutorPipeline, _EscritorFake, _CuarentenaFake]:
    escritor = _EscritorFake(escritos=[])
    cuarentena = _CuarentenaFake(registrados=[])

    def vincular_episodios(documentos, pepper):
        id_episodio_por_documento = {d.id_documento: f"episodio-{d.id_paciente}" for d in documentos}
        metadata_por_episodio = {
            f"episodio-{d.id_paciente}": MetadataEpisodio(id_paciente=d.id_paciente, fecha_ancla=d.fecha_estudio)
            for d in documentos
        }
        return ResultadoVinculacion(id_episodio_por_documento, metadata_por_episodio)

    def construir_registro(documento, claves, *, id_episodio, pepper, clave_documento, motor_pii=None):
        return RegistroAnonimizado(
            id_paciente=claves.id_paciente,
            id_episodio=id_episodio,
            tipo_documento=documento.tipo_documento,
            version_esquema=documento.version_esquema,
            fecha_estudio=documento.fecha_estudio,
            contenido=object(),
            adicionales={},
            clave_documento=clave_documento,
        )

    class _ParseadorFake:
        def parsear(self, texto):
            return texto

    class _ReconciliadorFake:
        def reconciliar(self, documento, texto):
            return None

    ejecutor = EjecutorPipeline(
        resolutor=object(),
        motor=object(),
        pepper=PEPPER,
        destino=escritor,
        cuarentena=cuarentena,
        dormir=lambda segundos: None,
        extraer=lambda artefacto: _documento(),
        detectar_tipo=lambda texto: TipoDocumento.LABORATORIO,
        obtener_parseador=lambda tipo: _ParseadorFake(),
        obtener_reconciliador=lambda tipo: _ReconciliadorFake(),
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="paciente-1", id_alt_paciente=None, version_clave=1),
        vincular_episodios=vincular_episodios,
        construir_registro=construir_registro,
        clasificar_pii=lambda documento, motor: None,
        coordinar_episodios=coordinar_episodios,
    )
    return ejecutor, escritor, cuarentena


def test_un_pendiente_sin_contabilizar_falla_ruidoso_en_vez_de_evaporarse() -> None:
    """4.1: coordinador falso que deja un episodio en `episodios_pendientes`.

    Hoy (antes de 4.3) `_coordinar_resueltos` ni lo aprueba ni lo aparta: el
    documento desaparece de `resultados` en silencio y `procesar_lote`
    devuelve una tupla vacía en vez de lanzar. Este test es RED contra ese
    código: `pytest.raises` falla porque no se lanza nada.
    """

    def coordinar_episodios_con_pendiente(documentos, *, pepper, corrida_cerrada):
        (documento,) = documentos
        return ResultadoCoordinacion(
            episodios_aprobados=(),
            episodios_pendientes=(_episodio_de(documento),),
            documentos_en_cuarentena={},
        )

    ejecutor, escritor, cuarentena = _construir_ejecutor(coordinar_episodios=coordinar_episodios_con_pendiente)

    with pytest.raises(RuntimeError, match="_GRUPO_ES_UNIDAD_COMPLETA"):
        ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("uno"))])

    assert escritor.escritos == []
    assert cuarentena.registrados == []


def test_el_caso_normal_sin_pendientes_devuelve_un_resultado_por_item() -> None:
    """4.2: sin pendientes, la igualdad `len(resultados) == len(items)` ya se
    sostenía hoy (el coordinador real nunca deja pendientes con
    `corrida_cerrada=True`) -- este test la deja escrita como contrato
    explícito, no como novedad de comportamiento."""

    def coordinar_episodios_normal(documentos, *, pepper, corrida_cerrada):
        aprobados = tuple(_episodio_de(documento) for documento in documentos)
        return ResultadoCoordinacion(
            episodios_aprobados=aprobados, episodios_pendientes=(), documentos_en_cuarentena={}
        )

    ejecutor, escritor, cuarentena = _construir_ejecutor(coordinar_episodios=coordinar_episodios_normal)

    items = [
        ItemLote(id_documento="doc-1", artefacto=_artefacto("uno")),
        ItemLote(id_documento="doc-2", artefacto=_artefacto("dos")),
    ]
    resultados = ejecutor.procesar_lote(items)

    assert len(resultados) == len(items)
    assert len(escritor.escritos) == 2
    assert cuarentena.registrados == []


def test_grupo_es_unidad_completa_no_es_parametro_publico() -> None:
    """4.4: exponerla sin la contabilidad detrás sería ofrecer la trampa con
    una perilla -- `procesar_lote` y `EjecutorPipeline.__init__` no la reciben."""
    import inspect

    from anonimizacion.pipeline.ejecutor import EjecutorPipeline

    assert "_GRUPO_ES_UNIDAD_COMPLETA" not in inspect.signature(EjecutorPipeline.__init__).parameters
    assert "_GRUPO_ES_UNIDAD_COMPLETA" not in inspect.signature(EjecutorPipeline.procesar_lote).parameters
    assert "corrida_cerrada" not in inspect.signature(EjecutorPipeline.procesar_lote).parameters
