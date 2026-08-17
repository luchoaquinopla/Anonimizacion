"""Test de integración (fix post-merge, ver `sdd/pdf-pii-anonymization/apply-progress`,
sección "Fix: persistencia del puente id_alt_paciente en Postgres entre corridas").

Reproduce el escenario real reportado por el usuario: `scripts/procesar_carpeta.py`
creaba un `ResolutorClaves()` VACÍO en cada corrida del script -- el puente
`id_alt_paciente -> id_paciente` que arma el laboratorio (Fase 6,
`pseudonimizacion/resolutor_claves.py`) se perdía al terminar el proceso. Si
el laboratorio de un paciente se procesaba HOY (una corrida) y el ECG del
MISMO paciente se procesaba MAÑANA (otra corrida separada), el ECG no
encontraba el puente aunque el laboratorio ya estuviera en la base --
terminaba en `CLAVE_PII_NO_RESUELTA` en vez de vincularse al `id_paciente`
real.

Este test ejercita `ResolutorClavesPostgres` (el adaptador que respalda el
mismo contrato de `ResolutorClaves` contra la tabla real `vinculo_paciente`
en vez de un dict en memoria) con DOS instancias de `EjecutorPipeline`
SEPARADAS, cada una con su PROPIA instancia NUEVA de `ResolutorClavesPostgres`,
sobre el MISMO engine -- exactamente lo que simula "dos corridas separadas
del programa" sin necesitar Postgres real. Usa `PRAGMA foreign_keys=ON`
(mismo patrón que `test_episodio_fk_real.py`) para que el escenario sea lo
más fiel posible al comportamiento real contra Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import event

from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento, FalloDocumento
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClavesPostgres
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base

from ..fixtures.v1 import documentos

PEPPER = b"pepper-puente-persistente-nunca-real"


def _engine_con_fk_reales() -> sa.Engine:
    """SQLite en memoria CON `PRAGMA foreign_keys=ON` activo por conexión.

    Ver `test_episodio_fk_real.py` para el porqué: sin este pragma, SQLite
    ignora los `ForeignKey(...)` declarados y deja pasar bugs que Postgres
    real rechazaría.
    """
    engine = sa.create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _activar_fk(conexion_dbapi, _registro) -> None:
        cursor = conexion_dbapi.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_ecg_de_otra_corrida_resuelve_el_puente_persistido_por_el_lab_de_una_corrida_anterior(
    tmp_path, motor: MotorPii
) -> None:
    nombre = "Marta Persistente Ocho"
    dni = "28666777"
    fecha_nac_lab = "12/06/1985"
    fecha_nac_ecg = "12-JUN-1985"

    # El engine representa la base persistente compartida entre corridas
    # reales del script (Postgres); acá un engine SQLite en memoria compartido
    # entre las dos instancias de EjecutorPipeline cumple el mismo rol: lo
    # único que se comparte entre "corrida 1" y "corrida 2" es el engine, NO
    # ninguna instancia de ResolutorClavesPostgres ni de EjecutorPipeline.
    engine = _engine_con_fk_reales()

    artefacto_lab = documentos.escribir_pdf(
        tmp_path,
        "lab-puente-1",
        documentos.texto_laboratorio(
            nombre=nombre, dni=dni, fecha_nac=fecha_nac_lab, numero_peticion="PET-PUENTE-1", fecha="05/02/2024"
        ),
    )

    # --- corrida 1 del programa: procesa el laboratorio ------------------------
    ejecutor_corrida_1 = EjecutorPipeline(
        resolutor=ResolutorClavesPostgres(EscritorPostgres(engine)),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
    )
    resultados_1 = ejecutor_corrida_1.procesar_lote(
        [ItemLote(id_documento="doc-lab-puente", artefacto=artefacto_lab)]
    )
    assert len(resultados_1) == 1
    assert isinstance(resultados_1[0], ExitoDocumento)

    # --- corrida 2, SEPARADA: instancia NUEVA de ResolutorClavesPostgres -------
    # (sin ningún estado en memoria heredado de la corrida 1 -- solo el
    # engine, que simula la base persistente real entre corridas del script)
    artefacto_ecg = documentos.escribir_pdf(
        tmp_path,
        "ecg-puente-1",
        documentos.texto_ecg(
            nombre=nombre, id_estudio="ECG-PUENTE-1", fecha="08-FEB-2024", fecha_nac=fecha_nac_ecg, edad_anios=38
        ),
    )
    ejecutor_corrida_2 = EjecutorPipeline(
        resolutor=ResolutorClavesPostgres(EscritorPostgres(engine)),  # instancia NUEVA
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
    )
    resultados_2 = ejecutor_corrida_2.procesar_lote(
        [ItemLote(id_documento="doc-ecg-puente", artefacto=artefacto_ecg)]
    )

    assert len(resultados_2) == 1
    resultado_ecg = resultados_2[0]
    # Si el puente NO se hubiera persistido, esto sería FalloDocumento con
    # CLAVE_PII_NO_RESUELTA en vez de ExitoDocumento -- esta aserción es la
    # que prueba el fix (RED antes de implementar ResolutorClavesPostgres y
    # conectarlo, GREEN después).
    assert isinstance(resultado_ecg, ExitoDocumento), (
        f"esperaba ExitoDocumento, el ECG cayó en cuarentena: {resultado_ecg.error}"
        if isinstance(resultado_ecg, FalloDocumento)
        else f"resultado inesperado: {resultado_ecg!r}"
    )
    assert resultado_ecg.id_paciente == resultados_1[0].id_paciente
