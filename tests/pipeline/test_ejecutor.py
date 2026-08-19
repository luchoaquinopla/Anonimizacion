"""Tests de `pipeline/ejecutor.py` (tasks.md 8.2, spec `batch-processing`).

Todas las etapas concretas (extraer/detectar_tipo/obtener_parseador/
resolver_claves/vincular_episodios/construir_registro) se inyectan como
fakes deterministas: este módulo testea AISLAMIENTO DE FALLO y POLÍTICA DE
REINTENTOS, no la lógica de cada etapa (eso ya está cubierto en sus propios
tests de unidad, PR1-PR6). Instanciar un `MotorPii`/`ResolutorClaves` real
acá sería lento (carga spaCy) e irrelevante para lo que se prueba.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.pipeline.ejecutor import BACKOFF_SEGUNDOS, MAX_REINTENTOS, EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento, FalloDocumento
from anonimizacion.pseudonimizacion.vinculacion import MetadataEpisodio, ResultadoVinculacion

PEPPER = b"pepper-de-test-no-usar-en-produccion"


def _artefacto(nombre: str) -> ArtefactoCrudo:
    return ArtefactoCrudo(uri=f"/fake/{nombre}.pdf", sha256="a" * 64, formato=FormatoArtefacto.PDF)


def _documento(id_paciente_sufijo: str, fecha: date = date(2026, 1, 10)) -> DocumentoParseado:
    return DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=None,  # no se usa: resolver_claves está fakeado en estos tests
        fecha_estudio=fecha,
        contenido=object(),
        adicionales={},
        fuentes=(),
    )


@dataclass
class _EscritorFake:
    escritos: list[RegistroAnonimizado]
    fallar_veces: int = 0
    episodios_escritos: list[str] = None  # type: ignore[assignment]
    orden_llamadas: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.episodios_escritos is None:
            self.episodios_escritos = []
        if self.orden_llamadas is None:
            self.orden_llamadas = []

    def escribir_episodio(self, *, id_episodio: str, id_paciente: str, fecha_ancla) -> None:
        self.orden_llamadas.append(f"episodio:{id_episodio}")
        self.episodios_escritos.append(id_episodio)

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        self.orden_llamadas.append(f"registro:{registro.id_episodio}")
        if self.fallar_veces > 0:
            self.fallar_veces -= 1
            raise ConnectionError("fallo transitorio simulado de DB")
        self.escritos.append(registro)


@dataclass
class _CuarentenaFake:
    registrados: list

    def registrar(self, error) -> None:
        self.registrados.append(error)


class _DormirFake:
    """Reemplaza `time.sleep`: no duerme de verdad, solo registra la espera pedida."""

    def __init__(self) -> None:
        self.llamadas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.llamadas.append(segundos)


def _construir_ejecutor(
    *,
    extraer,
    detectar_tipo=lambda texto: TipoDocumento.LABORATORIO,
    obtener_parseador=None,
    resolver_claves,
    vincular_episodios=None,
    construir_registro=None,
    escritor: _EscritorFake | None = None,
    cuarentena: _CuarentenaFake | None = None,
    dormir: _DormirFake | None = None,
):
    escritor = escritor or _EscritorFake(escritos=[])
    cuarentena = cuarentena or _CuarentenaFake(registrados=[])
    dormir = dormir or _DormirFake()

    if vincular_episodios is None:

        def vincular_episodios(documentos, pepper):  # noqa: ANN001, ANN201
            id_episodio_por_documento = {d.id_documento: f"episodio-{d.id_paciente}" for d in documentos}
            metadata_por_episodio = {
                f"episodio-{d.id_paciente}": MetadataEpisodio(id_paciente=d.id_paciente, fecha_ancla=d.fecha_estudio)
                for d in documentos
            }
            return ResultadoVinculacion(
                id_episodio_por_documento=id_episodio_por_documento,
                metadata_por_episodio=metadata_por_episodio,
            )
    if construir_registro is None:
        construir_registro = lambda documento, claves, *, id_episodio, pepper, motor_pii=None: RegistroAnonimizado(  # noqa: E731
            id_paciente=claves.id_paciente,
            id_episodio=id_episodio,
            tipo_documento=documento.tipo_documento,
            version_esquema=documento.version_esquema,
            fecha_estudio=documento.fecha_estudio,
            contenido=object(),
            adicionales={},
        )
    if obtener_parseador is None:
        class _ParseadorFake:
            def parsear(self, texto):
                return texto  # `extraer` ya devuelve el DocumentoParseado en estos tests

        obtener_parseador = lambda tipo: _ParseadorFake()  # noqa: E731

    ejecutor = EjecutorPipeline(
        resolutor=object(),
        motor=object(),
        pepper=PEPPER,
        destino=escritor,
        cuarentena=cuarentena,
        dormir=dormir,
        extraer=extraer,
        detectar_tipo=detectar_tipo,
        obtener_parseador=obtener_parseador,
        resolver_claves=resolver_claves,
        vincular_episodios=vincular_episodios,
        construir_registro=construir_registro,
        clasificar_pii=lambda documento, motor: None,
    )
    return ejecutor, escritor, cuarentena, dormir


def test_un_documento_con_layout_no_reconocido_no_aborta_el_resto_del_lote() -> None:
    # spec batch-processing, escenario "lote de 1000, 1 no reconocido" (acá con 3 por costo del test)
    items = [
        ItemLote(id_documento="doc-1", artefacto=_artefacto("uno")),
        ItemLote(id_documento="doc-2", artefacto=_artefacto("roto")),
        ItemLote(id_documento="doc-3", artefacto=_artefacto("tres")),
    ]

    def extraer_real(artefacto):
        return artefacto

    def detectar_tipo_real(artefacto):
        return TipoDocumento.TIPO_NO_RECONOCIDO if "roto" in artefacto.uri else TipoDocumento.LABORATORIO

    class _ParseadorPorTipo:
        def __init__(self, tipo):
            self._tipo = tipo

        def parsear(self, artefacto):
            if self._tipo is TipoDocumento.TIPO_NO_RECONOCIDO:
                raise ErrorParseo(codigo=CodigoErrorDocumento.TIPO_NO_RECONOCIDO, etapa="deteccion")
            return _documento(artefacto.uri)

    def resolver_claves(identidad, pepper, resolutor, *, id_documento, etapa):
        return ClavesPaciente(id_paciente=f"pac-{id_documento}", id_alt_paciente=None, version_clave=1)

    ejecutor, escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=extraer_real,
        detectar_tipo=detectar_tipo_real,
        obtener_parseador=lambda tipo: _ParseadorPorTipo(tipo),
        resolver_claves=resolver_claves,
    )

    resultados = ejecutor.procesar_lote(items)

    exitos = [r for r in resultados if isinstance(r, ExitoDocumento)]
    fallos = [r for r in resultados if isinstance(r, FalloDocumento)]

    assert {e.id_documento for e in exitos} == {"doc-1", "doc-3"}
    assert {f.id_documento for f in fallos} == {"doc-2"}
    assert fallos[0].error.codigo == CodigoErrorDocumento.TIPO_NO_RECONOCIDO
    assert len(escritor.escritos) == 2
    assert len(cuarentena.registrados) == 1


def test_error_deterministico_no_se_reintenta() -> None:
    intentos = {"n": 0}

    def extraer(artefacto):
        intentos["n"] += 1
        raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa="extraccion")

    ejecutor, _escritor, cuarentena, dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="x", id_alt_paciente=None, version_clave=1),
    )

    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("uno"))])

    assert intentos["n"] == 1  # nunca se reintenta un ErrorParseo
    assert dormir.llamadas == []
    assert len(resultados) == 1
    assert isinstance(resultados[0], FalloDocumento)
    assert resultados[0].error.codigo == CodigoErrorDocumento.PARSEO_INCOMPLETO
    assert cuarentena.registrados == [resultados[0].error]


def test_fallo_propaga_campo_y_pagina_seguros_a_cuarentena() -> None:
    def extraer(artefacto):
        raise ErrorParseo(
            codigo=CodigoErrorDocumento.EVIDENCIA_AUSENTE,
            etapa="reconciliacion",
            campo="ecg.vent_rate",
            pagina=1,
        )

    ejecutor, _escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="x", id_alt_paciente=None, version_clave=1),
    )

    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("uno"))])

    error = resultados[0].error
    assert error.campo == "ecg.vent_rate"
    assert error.pagina == 1
    assert cuarentena.registrados == [error]


def test_error_transitorio_se_reintenta_y_puede_tener_exito() -> None:
    # spec batch-processing, escenario "reintento exitoso tras fallo transitorio"
    intentos = {"n": 0}

    def extraer(artefacto):
        intentos["n"] += 1
        if intentos["n"] < 2:
            raise OSError("fallo de I/O transitorio simulado")
        return _documento("ok")

    ejecutor, escritor, cuarentena, dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="x", id_alt_paciente=None, version_clave=1),
    )

    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("uno"))])

    assert intentos["n"] == 2
    assert dormir.llamadas == [BACKOFF_SEGUNDOS[0]]
    assert len(resultados) == 1
    assert isinstance(resultados[0], ExitoDocumento)
    assert len(escritor.escritos) == 1
    assert cuarentena.registrados == []


def test_error_transitorio_agotado_va_a_cuarentena_tras_max_reintentos() -> None:
    intentos = {"n": 0}

    def extraer(artefacto):
        intentos["n"] += 1
        raise ConnectionError("nunca se recupera")

    ejecutor, _escritor, cuarentena, dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="x", id_alt_paciente=None, version_clave=1),
    )

    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("uno"))])

    assert intentos["n"] == MAX_REINTENTOS + 1  # intento inicial + MAX_REINTENTOS reintentos
    assert dormir.llamadas == list(BACKOFF_SEGUNDOS)
    assert isinstance(resultados[0], FalloDocumento)
    assert resultados[0].error.codigo == CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO
    assert resultados[0].error.etapa == "extraccion"
    assert cuarentena.registrados == [resultados[0].error]


def test_fallo_de_un_documento_no_impide_vincular_episodios_de_los_demas() -> None:
    def extraer(artefacto):
        if "roto" in artefacto.uri:
            raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa="extraccion")
        return _documento(artefacto.uri)

    llamados_con: list = []

    def vincular_episodios(documentos, pepper):
        llamados_con.extend(documentos)
        id_episodio_por_documento = {d.id_documento: f"episodio-{d.id_paciente}" for d in documentos}
        metadata_por_episodio = {
            f"episodio-{d.id_paciente}": MetadataEpisodio(id_paciente=d.id_paciente, fecha_ancla=d.fecha_estudio)
            for d in documentos
        }
        return ResultadoVinculacion(
            id_episodio_por_documento=id_episodio_por_documento, metadata_por_episodio=metadata_por_episodio
        )

    items = [
        ItemLote(id_documento="doc-1", artefacto=_artefacto("uno")),
        ItemLote(id_documento="doc-2", artefacto=_artefacto("roto")),
    ]

    ejecutor, escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda identidad, pepper, resolutor, *, id_documento, etapa: ClavesPaciente(
            id_paciente=f"pac-{id_documento}", id_alt_paciente=None, version_clave=1
        ),
        vincular_episodios=vincular_episodios,
    )

    resultados = ejecutor.procesar_lote(items)

    assert len(llamados_con) == 1  # solo el documento resuelto exitosamente llega a vinculación
    assert len(escritor.escritos) == 1
    assert len(cuarentena.registrados) == 1
    assert any(isinstance(r, ExitoDocumento) for r in resultados)
    assert any(isinstance(r, FalloDocumento) for r in resultados)


def test_error_transitorio_en_la_escritura_de_salida_tambien_se_reintenta() -> None:
    def extraer(artefacto):
        return _documento("ok")

    ejecutor, escritor, cuarentena, dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="x", id_alt_paciente=None, version_clave=1),
        escritor=_EscritorFake(escritos=[], fallar_veces=1),
    )

    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("uno"))])

    assert len(escritor.escritos) == 1
    assert isinstance(resultados[0], ExitoDocumento)
    assert dormir.llamadas == [BACKOFF_SEGUNDOS[0]]


def test_escribe_episodio_antes_del_registro_y_solo_una_vez_por_episodio_unico() -> None:
    # fix post-PR9: `resultado_laboratorio`/`medicion_ecg`/`medicion_eco`/
    # `texto_seccion_eco` son FK contra `episodio.id_episodio` -- si
    # `escribir_episodio` no se llama ANTES de `escribir_registro`, la
    # escritura del registro viola la FK (`ForeignKeyViolation` en Postgres
    # real). Acá se prueba con dos documentos del MISMO episodio: el episodio
    # debe escribirse UNA sola vez, antes que cualquiera de los dos registros.
    items = [
        ItemLote(id_documento="doc-1", artefacto=_artefacto("uno")),
        ItemLote(id_documento="doc-2", artefacto=_artefacto("dos")),
    ]

    def extraer(artefacto):
        return _documento(artefacto.uri)

    def vincular_episodios(documentos, pepper):
        # ambos documentos comparten el mismo episodio (mismo id_paciente/ancla)
        id_episodio_por_documento = {d.id_documento: "episodio-compartido" for d in documentos}
        metadata_por_episodio = {
            "episodio-compartido": MetadataEpisodio(id_paciente="pac-compartido", fecha_ancla=date(2026, 1, 10))
        }
        return ResultadoVinculacion(
            id_episodio_por_documento=id_episodio_por_documento, metadata_por_episodio=metadata_por_episodio
        )

    ejecutor, escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="pac-compartido", id_alt_paciente=None, version_clave=1),
        vincular_episodios=vincular_episodios,
    )

    resultados = ejecutor.procesar_lote(items)

    assert all(isinstance(r, ExitoDocumento) for r in resultados)
    # el episodio se escribió UNA sola vez, no una por documento
    assert escritor.episodios_escritos == ["episodio-compartido"]
    # y ANTES de cualquiera de los dos registros que lo referencian
    assert escritor.orden_llamadas[0] == "episodio:episodio-compartido"
    assert escritor.orden_llamadas.count("episodio:episodio-compartido") == 1
    assert escritor.orden_llamadas[1:] == ["registro:episodio-compartido", "registro:episodio-compartido"]


def test_lote_vacio_no_falla() -> None:
    ejecutor, escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: _documento("ok"),
        resolver_claves=lambda *a, **k: ClavesPaciente(id_paciente="x", id_alt_paciente=None, version_clave=1),
    )
    assert ejecutor.procesar_lote([]) == ()
    assert escritor.escritos == []
    assert cuarentena.registrados == []
