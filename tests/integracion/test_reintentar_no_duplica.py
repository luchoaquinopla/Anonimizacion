"""Idempotencia de `reintentar_corrida` contra Postgres REAL (feature `reanudacion-de-corridas`).

Este repositorio ya se comió un defecto grave por confiar en SQLite (no
aplica foreign keys por defecto) -- este test corre contra el Postgres real
de `docker-compose.yml` (puerto 5433), con el despachador real
(`despacho_paralelo.despachar_en_paralelo`, un `ProcessPoolExecutor` real) y
la ruta HTTP real (`crear_aplicacion_corridas`). Mismo patrón que
`tests/web/test_despacho_real_desde_el_panel.py`.

Escenario: UN documento de laboratorio solo (sin su ECG/eco) queda apartado
por `EPISODIO_INCOMPLETO` -- reintentable, y reproducible con certeza porque
el episodio sigue incompleto siempre (nunca aparece el estudio que falta).
Reintentar esa MISMA corrida dos veces seguidas (dos `POST .../reintentar`)
reencola el mismo documento dos veces -- el centinela es que `cuarentena`
sigue teniendo UNA sola fila para ese documento, nunca tres, y que `estudio`
sigue en cero: la guarda de `uq_cuarentena_corrida_documento` +
`EscritorCuarentena.registrar` (ya existente, spec `escritura-idempotente`)
protege el reintento exactamente igual que protege el primer intento.
"""

from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.salida.modelos_orm import Base, Cuarentena, Estudio
from anonimizacion.web.rutas_corridas import crear_aplicacion_corridas
from anonimizacion.web.servicio_corridas import ServicioCorridasReal

from ..fixtures.v1 import documentos

_CONNECT_REAL = socket.socket.connect
_URL_POSTGRES_REAL = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"


def _solicitar(aplicacion, metodo: str, ruta: str, cuerpo: bytes = b""):
    estado: list[str] = []
    encabezados: list[tuple[str, str]] = []
    respuesta = aplicacion(
        {
            "REQUEST_METHOD": metodo,
            "PATH_INFO": ruta,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(cuerpo)),
            "wsgi.input": io.BytesIO(cuerpo),
        },
        lambda codigo, headers: (estado.append(codigo), encabezados.extend(headers)),
    )
    return estado[0], json.loads(b"".join(respuesta))


@pytest.fixture()
def _engine_postgres_real(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    sonda = sa.create_engine(_URL_POSTGRES_REAL, connect_args={"connect_timeout": 3})
    try:
        with sonda.connect():
            pass
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexion es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_REAL}: {excepcion}")
    finally:
        sonda.dispose()

    engine = construir_engine_postgres(_URL_POSTGRES_REAL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.mark.postgres
def test_reintentar_dos_veces_no_duplica_cuarentena_ni_estudio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _engine_postgres_real
) -> None:
    monkeypatch.setenv("ANONIMIZACION_PEPPER", "pepper-test-reintentar-no-duplica-nunca-produccion")

    documentos.escribir_pdf(
        tmp_path,
        "01-lab-solo",
        documentos.texto_laboratorio(
            nombre="Bruno Sintetico Solo",
            dni="20888555",
            fecha_nac="06/06/1993",
            numero_peticion="PET-REINTENTO-1",
            fecha="10/01/2024",
        ),
    )

    lanzador = LanzadorCorrida(
        repositorio=RepositorioCorridas(_engine_postgres_real),
        cuarentena=EscritorCuarentena(_engine_postgres_real),
    )
    servicio = ServicioCorridasReal(
        lanzador=lanzador,
        motor=_engine_postgres_real,
        db_url=_URL_POSTGRES_REAL,
        procesos=1,
    )
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio, motor_lectura=_engine_postgres_real)

    estado, creada = _solicitar(aplicacion, "POST", "/corridas", json.dumps({"ruta": str(tmp_path)}).encode())
    assert estado == "202 Accepted"
    corrida_id = creada["id_corrida"]
    servicio.esperar_despachos_en_curso(timeout=120)

    with Session(_engine_postgres_real) as sesion:
        cuarentenas = sesion.scalars(sa.select(Cuarentena).where(Cuarentena.corrida_id == corrida_id)).all()
    assert len(cuarentenas) == 1, "el laboratorio solo debe quedar apartado por episodio incompleto"
    assert cuarentenas[0].codigo == "episodio_incompleto"

    for _ in range(2):
        estado_reintentar, cuerpo_reintentar = _solicitar(
            aplicacion, "POST", f"/corridas/{corrida_id}/reintentar"
        )
        assert estado_reintentar == "202 Accepted"
        assert cuerpo_reintentar["reintentados"] == 1
        assert cuerpo_reintentar["descartados_deterministicos"] == 0
        servicio.esperar_despachos_en_curso(timeout=120)

    with Session(_engine_postgres_real) as sesion:
        cuarentenas_finales = sesion.scalars(
            sa.select(Cuarentena).where(Cuarentena.corrida_id == corrida_id)
        ).all()
        estudios_finales = sesion.scalars(sa.select(Estudio).where(Estudio.corrida_id == corrida_id)).all()

    assert len(cuarentenas_finales) == 1, (
        "dos reintentos sobre el mismo documento no deben dejar tres filas de cuarentena -- "
        "la guarda de uq_cuarentena_corrida_documento protege el reintento igual que el primer intento"
    )
    assert estudios_finales == [], "el episodio sigue incompleto -- nunca debe aparecer un estudio publicado"
