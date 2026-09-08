"""Tests de `pipeline/ejecutor.py` (tasks.md 8.2, spec `batch-processing`).

Todas las etapas concretas (extraer/detectar_tipo/obtener_parseador/
resolver_claves/vincular_episodios/construir_registro) se inyectan como
fakes deterministas: este módulo testea AISLAMIENTO DE FALLO y POLÍTICA DE
REINTENTOS, no la lógica de cada etapa (eso ya está cubierto en sus propios
tests de unidad, PR1-PR6). Instanciar un `MotorPii`/`ResolutorClaves` real
acá sería lento (carga spaCy) e irrelevante para lo que se prueba.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.pipeline.coordinador_episodios import coordinar_episodios
from anonimizacion.pipeline.ejecutor import (
    BACKOFF_SEGUNDOS,
    MAX_REINTENTOS,
    EjecutorPipeline,
    ItemLote,
    _DocumentoResuelto,
)
from anonimizacion.pipeline.resultado import ExitoDocumento, FalloDocumento
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.pseudonimizacion.vinculacion import MetadataEpisodio, ResultadoVinculacion
from tests.fixtures.pdf_sintetico import crear_pdf_bytes_con_texto

PEPPER = b"pepper-de-test-no-usar-en-produccion"


def _artefacto(nombre: str) -> ArtefactoCrudo:
    return ArtefactoCrudo(uri=f"/fake/{nombre}.pdf", sha256="a" * 64, formato=FormatoArtefacto.PDF)


def _documento(
    id_paciente_sufijo: str,
    fecha: date = date(2026, 1, 10),
    tipo: TipoDocumento = TipoDocumento.LABORATORIO,
) -> DocumentoParseado:
    return DocumentoParseado(
        tipo_documento=tipo,
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
    obtener_reconciliador=None,
    clasificar_pii=None,
    coordinar_episodios_durables=None,
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
        construir_registro = lambda documento, claves, *, id_episodio, pepper, clave_documento, motor_pii=None, campos_no_extraidos=(): RegistroAnonimizado(  # noqa: E731
            id_paciente=claves.id_paciente,
            id_episodio=id_episodio,
            tipo_documento=documento.tipo_documento,
            version_esquema=documento.version_esquema,
            fecha_estudio=documento.fecha_estudio,
            contenido=object(),
            adicionales={},
            clave_documento=clave_documento,
            campos_no_extraidos=campos_no_extraidos,
        )
    if obtener_parseador is None:
        class _ParseadorFake:
            def parsear(self, texto):
                return texto  # `extraer` ya devuelve el DocumentoParseado en estos tests

        obtener_parseador = lambda tipo: _ParseadorFake()  # noqa: E731
    if obtener_reconciliador is None:
        class _ReconciliadorFake:
            def reconciliar(self, documento, texto):
                return ()

        obtener_reconciliador = lambda tipo: _ReconciliadorFake()  # noqa: E731
    if clasificar_pii is None:
        clasificar_pii = lambda documento, motor: None  # noqa: E731

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
        clasificar_pii=clasificar_pii,
        obtener_reconciliador=obtener_reconciliador,
        coordinar_episodios=coordinar_episodios_durables,
    )
    return ejecutor, escritor, cuarentena, dormir


def test_episodio_incompleto_queda_en_cuarentena_antes_de_anonimizar_o_publicar() -> None:
    llamadas: list[str] = []
    documentos = iter(
        [
            _documento("paciente", tipo=TipoDocumento.ECG),
            _documento("paciente", tipo=TipoDocumento.LABORATORIO),
        ]
    )

    class _ReconciliadorAprobado:
        def reconciliar(self, documento, texto):
            llamadas.append(f"reconciliacion:{documento.tipo_documento.value}")

    ejecutor, escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: next(documentos),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
        obtener_reconciliador=lambda tipo: _ReconciliadorAprobado(),
        clasificar_pii=lambda documento, motor: llamadas.append(f"pii:{documento.tipo_documento.value}"),
        construir_registro=lambda *a, **k: llamadas.append("anonimizacion"),
        coordinar_episodios_durables=coordinar_episodios,
    )

    resultados = ejecutor.procesar_lote(
        [
            ItemLote(id_documento="ecg-1", artefacto=_artefacto("ecg")),
            ItemLote(id_documento="lab-1", artefacto=_artefacto("lab")),
        ]
    )

    assert [resultado.id_documento for resultado in resultados] == ["ecg-1", "lab-1"]
    assert all(isinstance(resultado, FalloDocumento) for resultado in resultados)
    assert llamadas == ["reconciliacion:ecg", "pii:ecg", "reconciliacion:laboratorio", "pii:laboratorio"]
    assert escritor.escritos == []
    assert cuarentena.registrados == [resultado.error for resultado in resultados]


def test_episodio_completo_coordinado_emite_solo_despues_de_reconciliarlo() -> None:
    llamadas: list[str] = []
    documentos = iter(
        [
            _documento("paciente", tipo=TipoDocumento.ECG),
            _documento("paciente", tipo=TipoDocumento.LABORATORIO),
            _documento("paciente", tipo=TipoDocumento.ECOCARDIOGRAMA),
        ]
    )

    class _ReconciliadorAprobado:
        def reconciliar(self, documento, texto):
            llamadas.append(f"reconciliacion:{documento.tipo_documento.value}")

    ejecutor, escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: next(documentos),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
        obtener_reconciliador=lambda tipo: _ReconciliadorAprobado(),
        clasificar_pii=lambda documento, motor: llamadas.append(f"pii:{documento.tipo_documento.value}"),
        coordinar_episodios_durables=coordinar_episodios,
    )

    resultados = ejecutor.procesar_lote(
        [
            ItemLote(id_documento="ecg-1", artefacto=_artefacto("ecg")),
            ItemLote(id_documento="lab-1", artefacto=_artefacto("lab")),
            ItemLote(id_documento="eco-1", artefacto=_artefacto("eco")),
        ]
    )

    assert all(isinstance(resultado, ExitoDocumento) for resultado in resultados)
    assert len({resultado.id_episodio for resultado in resultados}) == 1
    assert len(escritor.escritos) == 3
    assert len(escritor.episodios_escritos) == 1
    assert cuarentena.registrados == []
    assert llamadas == [
        "reconciliacion:ecg",
        "pii:ecg",
        "reconciliacion:laboratorio",
        "pii:laboratorio",
        "reconciliacion:ecocardiograma",
        "pii:ecocardiograma",
    ]


def test_fallo_de_reconciliacion_bloquea_pii_claves_vinculo_y_salida() -> None:
    llamadas: list[str] = []

    class _ReconciliadorQueFalla:
        def reconciliar(self, documento, texto):
            llamadas.append("reconciliacion")
            raise ErrorParseo(
                CodigoErrorDocumento.COBERTURA_INCOMPLETA,
                etapa="reconciliacion",
                campo="ecg.vent_rate",
                pagina=1,
            )

    ejecutor, escritor, cuarentena, dormir = _construir_ejecutor(
        extraer=lambda artefacto: _documento("ok"),
        resolver_claves=lambda *a, **k: llamadas.append("claves"),
        obtener_reconciliador=lambda tipo: _ReconciliadorQueFalla(),
        clasificar_pii=lambda documento, motor: llamadas.append("pii"),
        vincular_episodios=lambda documentos, pepper: llamadas.append("vinculo"),
    )

    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("uno"))])

    assert llamadas == ["reconciliacion"]
    assert dormir.llamadas == []
    assert escritor.escritos == []
    assert len(cuarentena.registrados) == 1
    assert resultados[0].error.codigo == CodigoErrorDocumento.COBERTURA_INCOMPLETA
    assert resultados[0].error.tipo_documento is TipoDocumento.LABORATORIO


def test_fallo_de_pii_propaga_tipo_documento_a_cuarentena() -> None:
    def falla_pii(documento, motor):
        raise ErrorParseo(CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa="deteccion_pii")

    ejecutor, _escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: _documento("ok"),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
        clasificar_pii=falla_pii,
    )

    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-pii", artefacto=_artefacto("pii"))])

    assert resultados[0].error.tipo_documento is TipoDocumento.LABORATORIO
    assert cuarentena.registrados == [resultados[0].error]


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


# --- rewiring del puerto de ingesta (fase 7, openspec `puerto-de-ingesta`) --
#
# Prueba que `EjecutorPipeline` ya no necesita conocer el filesystem: el
# `extraer` por defecto pasa por `fuente.abrir(artefacto)` +
# `extraer_texto_de_flujo`, y un adaptador puramente en memoria (sin ninguna
# ruta real de disco) alcanza para procesar el lote de punta a punta. Si el
# ejecutor todavía hiciera `Path(artefacto.uri)` por su cuenta, este test
# fallaría con `FileNotFoundError` porque `memoria://doc1.pdf` no existe en
# el filesystem.


@dataclass
class _FuenteEnMemoria:
    """`FuenteDeArtefactos` mínimo que nunca toca disco: `abrir()` sirve
    bytes ya cargados en un diccionario, indexados por `uri`."""

    contenidos: dict[str, bytes]

    def listar(self) -> Iterator[ArtefactoCrudo]:
        raise NotImplementedError("este test no ejercita listar()")

    def abrir(self, artefacto: ArtefactoCrudo) -> io.BytesIO:
        return io.BytesIO(self.contenidos[artefacto.uri])


def test_extraer_por_defecto_usa_la_fuente_inyectada_sin_tocar_filesystem() -> None:
    contenido_pdf = crear_pdf_bytes_con_texto(["HEMATOLOGIA\nHematocrito 42%"])
    artefacto = ArtefactoCrudo(uri="memoria://doc1.pdf", sha256="a" * 64, formato=FormatoArtefacto.PDF)
    fuente = _FuenteEnMemoria(contenidos={artefacto.uri: contenido_pdf})
    escritor = _EscritorFake(escritos=[])
    cuarentena = _CuarentenaFake(registrados=[])

    texto_visto_por_el_parseador: list[str] = []

    class _ParseadorFake:
        def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
            texto_visto_por_el_parseador.append(texto.texto_completo)
            return _documento("paciente-1")

    class _ReconciliadorFake:
        def reconciliar(self, documento: object, texto: TextoExtraido) -> None:
            return None

    def resolver_claves(*_args: object, **_kwargs: object) -> ClavesPaciente:
        return ClavesPaciente(id_paciente="paciente-1", id_alt_paciente=None, version_clave=1)

    def vincular_episodios(documentos: list, pepper: bytes) -> ResultadoVinculacion:
        return ResultadoVinculacion(
            id_episodio_por_documento={d.id_documento: "episodio-1" for d in documentos},
            metadata_por_episodio={
                "episodio-1": MetadataEpisodio(id_paciente="paciente-1", fecha_ancla=date(2026, 1, 10))
            },
        )

    def construir_registro(
        documento: DocumentoParseado,
        claves: ClavesPaciente,
        *,
        id_episodio,
        pepper,
        clave_documento,
        motor_pii=None,
        campos_no_extraidos=(),
    ):
        return RegistroAnonimizado(
            id_paciente=claves.id_paciente,
            id_episodio=id_episodio,
            tipo_documento=documento.tipo_documento,
            version_esquema=documento.version_esquema,
            fecha_estudio=documento.fecha_estudio,
            contenido=object(),
            adicionales={},
            clave_documento=clave_documento,
            campos_no_extraidos=campos_no_extraidos,
        )

    ejecutor = EjecutorPipeline(
        resolutor=object(),
        motor=object(),
        pepper=PEPPER,
        destino=escritor,
        cuarentena=cuarentena,
        fuente=fuente,
        detectar_tipo=lambda texto: TipoDocumento.LABORATORIO,
        obtener_parseador=lambda tipo: _ParseadorFake(),
        obtener_reconciliador=lambda tipo: _ReconciliadorFake(),
        resolver_claves=resolver_claves,
        vincular_episodios=vincular_episodios,
        construir_registro=construir_registro,
        clasificar_pii=lambda documento, motor: None,
    )

    (resultado,) = ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=artefacto)])

    assert isinstance(resultado, ExitoDocumento)
    assert escritor.escritos[0].id_paciente == "paciente-1"
    assert "HEMATOLOGIA" in texto_visto_por_el_parseador[0]


def test_ejecutor_sin_fuente_ni_extraer_falla_explicito_en_la_construccion() -> None:
    with pytest.raises(ValueError, match="fuente"):
        EjecutorPipeline(
            resolutor=object(),
            motor=object(),
            pepper=PEPPER,
            destino=_EscritorFake(escritos=[]),
            cuarentena=_CuarentenaFake(registrados=[]),
        )


# --- clave_documento (spec `escritura-idempotente`) --------------------------


def test_documento_resuelto_expone_clave_documento() -> None:
    resuelto = _DocumentoResuelto(
        id_documento="doc-1",
        documento=_documento("paciente"),
        claves=ClavesPaciente(id_paciente="paciente", id_alt_paciente=None, version_clave=1),
        clave_documento=generar_clave_documento(PEPPER, "a" * 64),
    )
    assert resuelto.clave_documento == generar_clave_documento(PEPPER, "a" * 64)


def test_procesar_lote_deriva_y_propaga_clave_documento_hasta_el_registro() -> None:
    """Fija el recorrido completo `ItemLote.artefacto.sha256 ->
    _resolver_documento -> _emitir -> construir_registro` antes de tocar
    código (spec `escritura-idempotente`, Requisito 1)."""
    ejecutor, escritor, _cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: _documento("paciente"),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
    )

    artefacto = _artefacto("doc")
    ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=artefacto)])

    assert len(escritor.escritos) == 1
    esperado = generar_clave_documento(PEPPER, artefacto.sha256)
    assert escritor.escritos[0].clave_documento == esperado


def test_documento_corregido_mismo_id_documento_distinto_sha256_produce_clave_distinta() -> None:
    """Requisito 7, spec `escritura-idempotente`: si un documento se corrige
    en el origen (mismo `id_documento`, contenido/sha256 distinto), la
    `clave_documento` derivada MUST ser distinta -- consecuencia directa de
    Fases 1 y 4, sin código nuevo; este test fija el comportamiento
    explícitamente como red de seguridad."""
    ejecutor, escritor, _cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: _documento("paciente"),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
    )

    artefacto_original = ArtefactoCrudo(uri="/fake/doc.pdf", sha256="a" * 64, formato=FormatoArtefacto.PDF)
    artefacto_corregido = ArtefactoCrudo(uri="/fake/doc.pdf", sha256="b" * 64, formato=FormatoArtefacto.PDF)

    ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=artefacto_original)])
    ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=artefacto_corregido)])

    assert len(escritor.escritos) == 2
    clave_original, clave_corregida = escritor.escritos[0].clave_documento, escritor.escritos[1].clave_documento
    assert clave_original != clave_corregida


def test_item_lote_no_gano_ningun_campo_nuevo() -> None:
    """Requisito 2, "la cola conserva su forma": `ItemLote` sigue siendo
    exactamente `{id_documento, artefacto}`, sin campo nuevo."""
    campos = {campo.name for campo in ItemLote.__dataclass_fields__.values()}
    assert campos == {"id_documento", "artefacto"}


# --- motivos de episodio distinguibles de los de campo ----------------------


def test_los_motivos_de_episodio_tienen_codigo_propio() -> None:
    """"Falta el eco de este paciente" y "no pude verificar el potasio" son
    problemas operativos distintos y hasta ahora compartian codigo.

    La distincion no debe depender de una convencion implicita (que `campo`
    quede vacio): cualquier productor futuro que la rompa la arruinaria en
    silencio.
    """
    from anonimizacion.dominio.errores import CodigoErrorDocumento
    from anonimizacion.pipeline.ejecutor import _CODIGO_CUARENTENA_POR_MOTIVO
    from anonimizacion.pipeline.coordinador_episodios import MotivoCuarentenaEpisodio

    assert _CODIGO_CUARENTENA_POR_MOTIVO == {
        MotivoCuarentenaEpisodio.ASOCIACION_AMBIGUA: CodigoErrorDocumento.EPISODIO_AMBIGUO,
        MotivoCuarentenaEpisodio.ESTUDIOS_FALTANTES: CodigoErrorDocumento.EPISODIO_INCOMPLETO,
    }
    # Los codigos de cobertura quedan exclusivos del nivel campo.
    assert CodigoErrorDocumento.EPISODIO_AMBIGUO is not CodigoErrorDocumento.COBERTURA_AMBIGUA
    assert CodigoErrorDocumento.EPISODIO_INCOMPLETO is not CodigoErrorDocumento.COBERTURA_INCOMPLETA


def test_la_coordinacion_es_una_etapa_propia() -> None:
    """Antes usaba `reconciliacion`, el mismo string que el nivel campo."""
    from anonimizacion.pipeline.etapas import Etapa

    assert Etapa.COORDINACION.value == "coordinacion"
    assert Etapa.COORDINACION.value != Etapa.RECONCILIACION.value


# --- corrida_id viaja como parámetro del lote (spec `trazabilidad-por-corrida`,
# design.md Decisión 1 y 2) --------------------------------------------------


def test_procesar_lote_propaga_corrida_id_al_registro_emitido() -> None:
    """5.2: `corrida_id` llega a `RegistroAnonimizado.corrida_id` vía `_emitir`."""
    ejecutor, escritor, _cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: _documento("paciente"),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
    )

    ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("doc"))], corrida_id="c1")

    assert len(escritor.escritos) == 1
    assert escritor.escritos[0].corrida_id == "c1"


def test_procesar_lote_propaga_corrida_id_al_error_apartado() -> None:
    """5.3: camino de fallo -- un ítem apartado produce `ErrorDocumento.corrida_id == "c1"`."""

    def extraer(artefacto):
        raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa="extraccion")

    ejecutor, _escritor, cuarentena, _dormir = _construir_ejecutor(
        extraer=extraer,
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
    )

    resultados = ejecutor.procesar_lote(
        [ItemLote(id_documento="doc-1", artefacto=_artefacto("doc"))], corrida_id="c1"
    )

    assert isinstance(resultados[0], FalloDocumento)
    assert resultados[0].error.corrida_id == "c1"
    assert cuarentena.registrados == [resultados[0].error]


def test_procesar_lote_sin_corrida_id_conserva_none() -> None:
    """Sin `corrida_id` explícito, el default sigue siendo `None` -- no romper
    llamadores existentes que todavía no conocen su corrida."""
    ejecutor, escritor, _cuarentena, _dormir = _construir_ejecutor(
        extraer=lambda artefacto: _documento("paciente"),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente", None, 1),
    )

    ejecutor.procesar_lote([ItemLote(id_documento="doc-1", artefacto=_artefacto("doc"))])

    assert escritor.escritos[0].corrida_id is None

