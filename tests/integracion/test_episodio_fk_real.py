"""Test de integración (fix post-PR9, ver `sdd/pdf-pii-anonymization/apply-progress`).

`EjecutorPipeline._emitir` llamaba `self._destino.escribir_registro(registro)`
sin haber llamado antes `self._destino.escribir_episodio(...)` -- como
`resultado_laboratorio`/`medicion_ecg`/`medicion_eco`/`texto_seccion_eco` son
FK contra `episodio.id_episodio` (`salida/modelos_orm.py`), esto revienta con
`psycopg.errors.ForeignKeyViolation` contra Postgres real (reproducido con un
script manual fuera del repo, no un test).

NINGÚN test existente hubiera detectado esto: tanto
`tests/salida/destinos/test_postgres.py` como el resto de
`tests/integracion/` (`test_lote_aislamiento.py`, `test_e2e_linkage.py`)
corren contra `sqlite:///:memory:` SIN `PRAGMA foreign_keys=ON` -- SQLite NO
aplica los FKs declarados por defecto, así que escribir una fila hija sin el
padre simplemente... funciona, en silencio. Este archivo activa el pragma
explícitamente para replicar la integridad referencial real de Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import event

from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base, Episodio, ResultadoLaboratorio

from ..fixtures.v1 import documentos

PEPPER = b"pepper-fk-real-integracion-nunca-real"


def _engine_con_fk_reales() -> sa.Engine:
    """SQLite en memoria CON `PRAGMA foreign_keys=ON` activo por conexión.

    Sin este pragma explícito, SQLite ignora los `ForeignKey(...)` declarados
    en `modelos_orm.py` -- ver docstring del módulo para por qué eso dejó
    pasar el bug en toda la suite existente.
    """
    engine = sa.create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _activar_fk(conexion_dbapi, _registro) -> None:
        cursor = conexion_dbapi.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_episodio_se_persiste_antes_que_las_filas_hijas_con_fk_reales_activos(tmp_path, motor: MotorPii) -> None:
    artefacto = documentos.escribir_pdf(
        tmp_path,
        "lab-fk-real",
        documentos.texto_laboratorio(
            nombre="Marta Sintetica Siete",
            dni="24999888",
            fecha_nac="01/01/1980",
            numero_peticion="PET-FK-1",
            fecha="05/02/2024",
        ),
    )

    engine = _engine_con_fk_reales()
    ejecutor = EjecutorPipeline(
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
    )

    # sin el fix, esto lanza `sqlite3.IntegrityError: FOREIGN KEY constraint
    # failed` al intentar insertar `resultado_laboratorio` sin que exista
    # antes la fila `episodio` -- equivalente sintético del
    # `psycopg.errors.ForeignKeyViolation` real reproducido contra Postgres.
    resultados = ejecutor.procesar_lote([ItemLote(id_documento="doc-fk", artefacto=artefacto)])

    assert len(resultados) == 1
    assert isinstance(resultados[0], ExitoDocumento)

    with sa.orm.Session(engine) as sesion:
        episodios = sesion.scalars(sa.select(Episodio)).all()
        filas_lab = sesion.scalars(sa.select(ResultadoLaboratorio)).all()

    assert len(episodios) == 1
    assert episodios[0].id_episodio == resultados[0].id_episodio
    assert len(filas_lab) >= 1
    assert all(fila.id_episodio == episodios[0].id_episodio for fila in filas_lab)
