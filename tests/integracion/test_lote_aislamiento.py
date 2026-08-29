"""Test de integración (tasks.md 11.2, spec `batch-processing`, escenario "1 no reconocido en un lote").

A diferencia de `tests/pipeline/test_ejecutor.py` (PR7, fakes deterministas
para aislar la lógica de reintentos/aislamiento), este test conecta
`EjecutorPipeline` a componentes REALES de punta a punta -- extracción
PyMuPDF sobre PDFs sintéticos en disco, detección de tipo, parsers reales,
`MotorPii` real, pseudonimización HMAC real, y storage SQLite real (mismo
precedente que `tests/salida/test_migraciones.py`) -- para demostrar que el
aislamiento de fallo por documento sostiene con el pipeline completo
conectado, no solo con las etapas fakeadas.
"""

from __future__ import annotations

from dataclasses import replace

import sqlalchemy as sa

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.ingesta.fuente import FuenteLocal
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento, FalloDocumento
from anonimizacion.parseo.registro import obtener_parseador
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import (
    Base,
    Cuarentena,
    MedicionEcg,
    MedicionEco,
    ResultadoLaboratorio,
    TextoSeccionEco,
    VinculoPaciente,
)

from ..fixtures.v1 import documentos

PEPPER = b"pepper-integracion-11-2-nunca-real"


def _engine_sqlite() -> sa.Engine:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def test_un_documento_con_layout_no_reconocido_en_lote_no_aborta_el_resto(tmp_path, motor: MotorPii) -> None:
    # spec batch-processing, escenario "lote de 1000, 1 no reconocido" -- acá con
    # 3 documentos reales por costo del test (mismo espíritu que test_ejecutor.py PR7).
    artefacto_ok_1 = documentos.escribir_pdf(
        tmp_path,
        "lab-ok-1",
        documentos.texto_laboratorio(
            nombre="Pedro Sintetico Uno",
            dni="20111222",
            fecha_nac="02/02/1975",
            numero_peticion="PET-A1",
            fecha="10/01/2024",
        ),
    )
    artefacto_roto = documentos.escribir_pdf(tmp_path, "roto", documentos.texto_layout_no_reconocido())
    artefacto_ok_2 = documentos.escribir_pdf(
        tmp_path,
        "lab-ok-2",
        documentos.texto_laboratorio(
            nombre="Sofia Sintetica Dos",
            dni="20333444",
            fecha_nac="08/08/1988",
            numero_peticion="PET-A2",
            fecha="11/01/2024",
        ),
    )

    engine = _engine_sqlite()
    ejecutor = EjecutorPipeline(
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
        fuente=FuenteLocal(raices=(tmp_path,), directorio=tmp_path),
    )

    items = [
        ItemLote(id_documento="doc-1", artefacto=artefacto_ok_1),
        ItemLote(id_documento="doc-2-roto", artefacto=artefacto_roto),
        ItemLote(id_documento="doc-3", artefacto=artefacto_ok_2),
    ]

    resultados = ejecutor.procesar_lote(items)

    exitos = [r for r in resultados if isinstance(r, ExitoDocumento)]
    fallos = [r for r in resultados if isinstance(r, FalloDocumento)]

    assert {e.id_documento for e in exitos} == {"doc-1", "doc-3"}
    assert {f.id_documento for f in fallos} == {"doc-2-roto"}
    assert fallos[0].error.codigo == CodigoErrorDocumento.TIPO_NO_RECONOCIDO

    # el documento fallido queda registrado con estado de fallo explícito en cuarentena
    with sa.orm.Session(engine) as sesion:
        filas_cuarentena = sesion.scalars(sa.select(Cuarentena)).all()
        filas_lab = sesion.scalars(sa.select(ResultadoLaboratorio)).all()

    assert len(filas_cuarentena) == 1
    assert filas_cuarentena[0].id_documento == "doc-2-roto"
    assert filas_cuarentena[0].codigo == CodigoErrorDocumento.TIPO_NO_RECONOCIDO.value

    # los 2 documentos restantes se procesaron y emitieron normalmente
    assert len(filas_lab) == 4  # 2 resultados por lab x 2 labs exitosos


def test_omisiones_sinteticas_de_cada_tipo_van_a_cuarentena_antes_de_pii_y_salida(tmp_path, motor: MotorPii) -> None:
    """El parser falso omite un dato tras usar el parser real; el PDF conserva la evidencia."""
    artefactos = [
        documentos.escribir_pdf(
            tmp_path,
            "ecg-omitido",
            documentos.texto_ecg(
                nombre="Ecg Sintetico",
                id_estudio="ECG-1",
                fecha="10-JAN-2024",
                fecha_nac="02-FEB-1975",
                edad_anios=48,
            ),
        ),
        documentos.escribir_pdf(
            tmp_path,
            "lab-omitido",
            documentos.texto_laboratorio(
                nombre="Laboratorio Sintetico",
                dni="20111222",
                fecha_nac="02/02/1975",
                numero_peticion="PET-1",
                fecha="10/01/2024",
            ),
        ),
        documentos.escribir_pdf(
            tmp_path,
            "eco-omitido",
            documentos.texto_eco(
                nombre="Eco Sintetico",
                dni="20333444",
                numero_estudio="ECO-1",
                fecha="10/01/2024",
            ),
        ),
    ]

    class _ParseadorQueOmiteCampo:
        def __init__(self, tipo):
            self._tipo = tipo
            self._real = obtener_parseador(tipo)

        def parsear(self, texto):
            documento = self._real.parsear(texto)
            if self._tipo.value == "ecg":
                return replace(
                    documento,
                    contenido=replace(documento.contenido, vent_rate=None),
                    fuentes=tuple(f for f in documento.fuentes if f.id_campo != "ecg.vent_rate"),
                )
            if self._tipo.value == "laboratorio":
                return replace(
                    documento,
                    contenido=replace(documento.contenido, resultados=documento.contenido.resultados[:1]),
                    fuentes=tuple(
                        f
                        for f in documento.fuentes
                        if not (f.id_campo == "laboratorio.resultado" and f.ordinal > 0)
                    ),
                )
            return replace(
                documento,
                contenido=replace(documento.contenido, medidas=documento.contenido.medidas[:1]),
                fuentes=tuple(
                    f
                    for f in documento.fuentes
                    if not (f.id_campo == "eco.medida" and f.ordinal > 0)
                ),
            )

    engine = _engine_sqlite()
    ejecutor = EjecutorPipeline(
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
        fuente=FuenteLocal(raices=(tmp_path,), directorio=tmp_path),
        obtener_parseador=lambda tipo: _ParseadorQueOmiteCampo(tipo),
    )

    resultados = ejecutor.procesar_lote(
        [ItemLote(id_documento=f"doc-{indice}", artefacto=artefacto) for indice, artefacto in enumerate(artefactos)]
    )

    assert all(isinstance(resultado, FalloDocumento) for resultado in resultados)
    assert {resultado.error.codigo for resultado in resultados} == {CodigoErrorDocumento.COBERTURA_INCOMPLETA}
    assert {resultado.error.etapa for resultado in resultados} == {"reconciliacion"}

    with sa.orm.Session(engine) as sesion:
        assert len(sesion.scalars(sa.select(Cuarentena)).all()) == 3
        assert sesion.scalars(sa.select(VinculoPaciente)).all() == []
        assert sesion.scalars(sa.select(ResultadoLaboratorio)).all() == []
        assert sesion.scalars(sa.select(MedicionEcg)).all() == []
        assert sesion.scalars(sa.select(MedicionEco)).all() == []
        assert sesion.scalars(sa.select(TextoSeccionEco)).all() == []
