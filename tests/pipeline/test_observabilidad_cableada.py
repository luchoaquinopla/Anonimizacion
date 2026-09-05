"""Observabilidad cableada en la raíz de composición (design.md, Decisión 7).

`ColectorMetricas`/`BitacoraSegura` (`observabilidad/`) estaban construidos,
testeados y con CERO imports de producción hasta este tramo. Los tests de acá
verifican la CONDUCTA real -- no la forma del código -- para que ninguna pieza
de observabilidad se declare terminada sin que algo la ejercite de punta a
punta por la raíz de composición de producción
(`trabajadores/tareas.py::construir_fabrica_ejecutor`), el mismo molde que
`tests/integracion/test_wiring_produccion.py`. Un test de `inspect.getsource`
no alcanza acá: la afirmación es sobre si las observaciones LLEGAN, no sobre
si el cableado está escrito.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")

import pytest
import sqlalchemy as sa

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.observabilidad.bitacora_segura import BitacoraSegura
from anonimizacion.observabilidad.metricas import MetricasEnMemoria
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves
from anonimizacion.pseudonimizacion.vinculacion import MetadataEpisodio, ResultadoVinculacion
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.trabajadores import tareas

from ..fixtures.v1 import documentos

PEPPER = b"pepper-observabilidad-cableada-nunca-real"


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


def _grupo_completo(directorio, sufijo: str):
    """Mismo grupo sintético de `test_wiring_produccion.py`: los tres tipos son
    obligatorios para que la validación de episodio de producción no lo aparte
    entero antes de llegar a `_emitir`."""
    return [
        documentos.escribir_pdf(
            directorio,
            f"lab-{sufijo}",
            documentos.texto_laboratorio(
                nombre="Beto Sintetico Observado",
                dni="20666999",
                fecha_nac="03/03/1990",
                numero_peticion=f"PET-{sufijo}",
                fecha="10/02/2024",
            ),
        ),
        documentos.escribir_pdf(
            directorio,
            f"ecg-{sufijo}",
            documentos.texto_ecg(
                nombre="Beto Sintetico Observado",
                id_estudio=f"ECG-{sufijo}",
                fecha="11-FEB-2024",
                fecha_nac="03-MAR-1990",
                edad_anios=34,
                sexo="Male",
            ),
        ),
        documentos.escribir_pdf(
            directorio,
            f"eco-{sufijo}",
            documentos.texto_eco(
                nombre="Beto Sintetico Observado",
                dni="20666999",
                numero_estudio=f"ECO-{sufijo}",
                fecha="12/02/2024",
            ),
        ),
    ]


def _referencias(artefactos):
    return [
        {"id_documento": f"doc-{indice}", "uri": a.uri, "sha256": a.sha256}
        for indice, a in enumerate(artefactos)
    ]


def _engine_con_esquema() -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


class _ColectorEspia:
    """Espía de `ColectorMetricas`: registra cada llamada recibida, no valida nada."""

    def __init__(self) -> None:
        self.documentos_procesados: list[TipoDocumento] = []
        self.fallos: list[CodigoErrorDocumento] = []
        self.duraciones: list[tuple[str, float]] = []

    def incrementar_documento_procesado(self, tipo_documento: TipoDocumento) -> None:
        self.documentos_procesados.append(tipo_documento)

    def incrementar_fallo(self, codigo: CodigoErrorDocumento) -> None:
        self.fallos.append(codigo)

    def observar_duracion_ms(self, etapa: str, duracion_ms: float) -> None:
        self.duraciones.append((etapa, duracion_ms))


class _ColectorQueExplota:
    """Cumple `ColectorMetricas` por tipado estructural, pero revienta en cada método."""

    def incrementar_documento_procesado(self, tipo_documento: TipoDocumento) -> None:
        raise RuntimeError("colector roto: incrementar_documento_procesado")

    def incrementar_fallo(self, codigo: CodigoErrorDocumento) -> None:
        raise RuntimeError("colector roto: incrementar_fallo")

    def observar_duracion_ms(self, etapa: str, duracion_ms: float) -> None:
        raise RuntimeError("colector roto: observar_duracion_ms")


class _BitacoraEspia:
    """Espía de `BitacoraSegura`: guarda una copia de cada evento recibido."""

    def __init__(self) -> None:
        self.eventos: list[dict] = []

    def registrar(self, evento, *, nivel: int = 20) -> dict:
        registrado = dict(evento)
        self.eventos.append(registrado)
        return registrado


def test_la_fabrica_cablea_la_observabilidad(tmp_path, motor: MotorPii) -> None:
    """7.1: el espía inyectado por la fábrica tiene que recibir observaciones de
    un grupo real procesado por `tareas.procesar_grupo` -- no un doble del
    ejecutor ni una llamada directa a `EjecutorPipeline`."""
    artefactos = _grupo_completo(tmp_path, "observado")
    engine = _engine_con_esquema()
    espia_metricas = _ColectorEspia()
    espia_bitacora = _BitacoraEspia()

    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(tmp_path,),
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
        metricas=espia_metricas,
        bitacora=espia_bitacora,
    )
    tareas.configurar_ejecutor(fabrica)
    try:
        resultados = tareas.procesar_grupo("corrida-observada", _referencias(artefactos))
    finally:
        tareas._fabrica_ejecutor = None

    assert len(resultados) == 3
    assert {resultado["estado"] for resultado in resultados} == {"exito"}
    assert len(espia_metricas.documentos_procesados) == 3
    assert len(espia_metricas.duraciones) > 0
    assert len(espia_bitacora.eventos) == 3


def test_sin_inyeccion_explicita_igual_hay_colector(tmp_path, motor: MotorPii) -> None:
    """7.3: cubre el agujero del test anterior -- conservar el punto de
    inyección y borrar el default de producción dejaría el test 7.1 en verde
    y producción ciega igual."""
    engine = _engine_con_esquema()
    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(tmp_path,),
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
    )

    ejecutor = fabrica()

    assert isinstance(ejecutor._metricas, MetricasEnMemoria)
    assert isinstance(ejecutor._bitacora, BitacoraSegura)


def test_un_colector_que_explota_no_tumba_el_grupo(tmp_path, motor: MotorPii) -> None:
    """7.5: invariante 3 de la propuesta -- la observabilidad es accesoria."""
    artefactos = _grupo_completo(tmp_path, "resiliente")
    engine = _engine_con_esquema()

    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(tmp_path,),
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
        metricas=_ColectorQueExplota(),
    )
    tareas.configurar_ejecutor(fabrica)
    try:
        resultados = tareas.procesar_grupo("corrida-resiliente", _referencias(artefactos))
    finally:
        tareas._fabrica_ejecutor = None

    assert len(resultados) == 3
    assert {resultado["estado"] for resultado in resultados} == {"exito"}


class _EscritorFake:
    def escribir_episodio(self, *, id_episodio: str, id_paciente: str, fecha_ancla) -> None:
        pass

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        pass


@dataclass
class _CuarentenaFake:
    registrados: list

    def registrar(self, error) -> None:
        self.registrados.append(error)


def _vincular_episodios_fake(documentos, pepper):
    id_episodio_por_documento = {d.id_documento: f"episodio-{d.id_paciente}" for d in documentos}
    metadata_por_episodio = {
        f"episodio-{d.id_paciente}": MetadataEpisodio(id_paciente=d.id_paciente, fecha_ancla=d.fecha_estudio)
        for d in documentos
    }
    return ResultadoVinculacion(
        id_episodio_por_documento=id_episodio_por_documento,
        metadata_por_episodio=metadata_por_episodio,
    )


def _construir_registro_fake(documento, claves, *, id_episodio, pepper, clave_documento, motor_pii=None):
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


def test_bitacora_registra_exactamente_una_vez_por_resultado() -> None:
    """7.7: `bitacora.registrar(resultado.resumen_trazable())` una vez por
    resultado, al cerrar `procesar_lote` -- no por documento resuelto, no por
    intento de reintento."""
    espia_bitacora = _BitacoraEspia()
    documento_ok = DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=None,
        fecha_estudio=date(2024, 1, 10),
        contenido=object(),
        adicionales={},
        fuentes=(),
    )

    def extraer(artefacto: ArtefactoCrudo):
        if artefacto.uri.endswith("malo.pdf"):
            raise ErrorParseo(CodigoErrorDocumento.TIPO_NO_RECONOCIDO, etapa="extraccion")
        return documento_ok

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
        destino=_EscritorFake(),
        cuarentena=_CuarentenaFake(registrados=[]),
        extraer=extraer,
        detectar_tipo=lambda texto: TipoDocumento.LABORATORIO,
        obtener_parseador=lambda tipo: _ParseadorFake(),
        obtener_reconciliador=lambda tipo: _ReconciliadorFake(),
        resolver_claves=lambda *a, **k: ClavesPaciente("paciente-1", None, 1),
        vincular_episodios=_vincular_episodios_fake,
        construir_registro=_construir_registro_fake,
        clasificar_pii=lambda documento, motor: None,
        bitacora=espia_bitacora,
    )

    resultados = ejecutor.procesar_lote(
        [
            ItemLote(
                id_documento="ok-1",
                artefacto=ArtefactoCrudo(uri="/x/bueno.pdf", sha256="a" * 64, formato=FormatoArtefacto.PDF),
            ),
            ItemLote(
                id_documento="malo-1",
                artefacto=ArtefactoCrudo(uri="/x/malo.pdf", sha256="b" * 64, formato=FormatoArtefacto.PDF),
            ),
        ]
    )

    assert len(resultados) == 2
    assert espia_bitacora.eventos == [resultado.resumen_trazable() for resultado in resultados]
