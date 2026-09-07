"""Prueba de punta a punta: la ruta HTTP real procesa documentos de verdad.

Feature `despachador-desde-el-panel`: hasta este cambio, `POST /corridas`
inventariaba y descartaba el resultado a propósito -- ningún test HTTP
verificaba que un documento terminara publicado en `estudio`. Patrón que
apareció seis veces en este repositorio (según el mensaje de la tarea): "algo
verde que valida un cableado que producción no usa". Este módulo existe para
que ESTE cambio no sea el séptimo -- ejercita la ruta WSGI real
(`crear_aplicacion_corridas`), el servicio real (`ServicioCorridasReal`), el
despachador real (`despacho_paralelo.despachar_en_paralelo`, un
`ProcessPoolExecutor` real) y Postgres real, y verifica que el documento
quedó publicado en `estudio` -- no que se llamó a una función.

Marcado `pytest.mark.postgres` (mismo patrón que
`tests/scripts/test_procesar_carpeta.py::test_el_script_despacha_dos_pacientes_en_procesos_reales_distintos_contra_postgres_real`):
se salta solo si Postgres real (`docker-compose.yml`, puerto 5433) no
responde.
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
from anonimizacion.salida.modelos_orm import Base, CorridaOrm, Estudio
from anonimizacion.web.rutas_corridas import crear_aplicacion_corridas
from anonimizacion.web.servicio_corridas import ServicioCorridasReal

from ..fixtures.v1 import documentos

# Ver el comentario junto a `_CONNECT_REAL` en
# `tests/scripts/test_servir_panel.py`/`tests/scripts/test_procesar_carpeta.py`:
# captura la implementación real ANTES de que
# `tests/conftest.py::_bloquear_llamadas_de_red_reales` la parchee a nivel de
# sesión.
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
    """Motor contra el Postgres real de `docker-compose.yml`, o `skip` si no
    responde -- mismo patrón que `tests/scripts/test_procesar_carpeta.py`."""
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
def test_post_corridas_despacha_de_verdad_y_publica_el_estudio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _engine_postgres_real
) -> None:
    """El centinela de la tarea: `POST /corridas` tiene que dejar un
    `Estudio` real en Postgres, publicado por un PROCESO HIJO real -- no sólo
    devolver `202` sobre un inventario que nadie procesó.

    Un solo paciente/episodio (laboratorio + ECG + eco) para que la corrida
    termine rápido; `procesos=1` sigue usando un `ProcessPoolExecutor` real
    de un worker (ver el docstring de `_despachar_y_cerrar` sobre por qué
    NUNCA se usa el camino secuencial-en-el-servidor)."""
    monkeypatch.setenv("ANONIMIZACION_PEPPER", "pepper-test-despacho-real-desde-el-panel-nunca-produccion")

    documentos.escribir_pdf(
        tmp_path,
        "01-lab",
        documentos.texto_laboratorio(
            nombre="Ana Sintetica Despacho",
            dni="20777444",
            fecha_nac="05/05/1992",
            numero_peticion="PET-DESPACHO-1",
            fecha="10/01/2024",
        ),
    )
    documentos.escribir_pdf(
        tmp_path,
        "02-ecg",
        documentos.texto_ecg(
            nombre="Ana Sintetica Despacho",
            id_estudio="ECG-DESPACHO-1",
            fecha="11-JAN-2024",
            fecha_nac="05-MAY-1992",
            edad_anios=31,
            sexo="Female",
        ),
    )
    documentos.escribir_pdf(
        tmp_path,
        "03-eco",
        documentos.texto_eco(
            nombre="Ana Sintetica Despacho",
            dni="20777444",
            numero_estudio="ECO-DESPACHO-1",
            fecha="12/01/2024",
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

    # El corazón de este test: esperar el despacho REAL (proceso hijo real,
    # Postgres real) y comprobar el efecto real -- no una llamada, un
    # `Estudio` publicado.
    servicio.esperar_despachos_en_curso(timeout=120)

    with Session(_engine_postgres_real) as sesion:
        fila_corrida = sesion.get(CorridaOrm, corrida_id)
        estudios = sesion.scalars(sa.select(Estudio).where(Estudio.corrida_id == corrida_id)).all()

    assert fila_corrida is not None
    assert fila_corrida.estado == "completada", (
        "la corrida tiene que cerrar COMPLETADA sola, sin que el test la marque a mano"
    )
    assert len(estudios) == 3, "los tres estudios del episodio (lab/ecg/eco) tienen que quedar publicados"
    tipos_publicados = {estudio.tipo_documento for estudio in estudios}
    assert tipos_publicados == {"laboratorio", "ecg", "ecocardiograma"}

    # `GET /corridas/{id}` (la ruta que el médico consulta desde el panel)
    # también tiene que reflejar el desenlace real -- no sólo la tabla.
    estado_consulta, consultada = _solicitar(aplicacion, "GET", f"/corridas/{corrida_id}")
    assert estado_consulta == "200 OK"
    assert consultada == {
        "id_corrida": corrida_id,
        "estado": "completada",
        "documentos_pendientes": 0,
        "cuarentenas": 0,
    }


@pytest.mark.postgres
def test_post_corridas_dos_veces_seguidas_rechaza_la_segunda_mientras_la_primera_no_cerro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _engine_postgres_real
) -> None:
    """Decisión "dos corridas a la vez", de punta a punta por la ruta HTTP
    real: mientras la primera corrida sigue activa, la segunda petición
    recibe `409`, no un segundo despacho compitiendo por el mismo
    presupuesto de memoria."""
    monkeypatch.setenv("ANONIMIZACION_PEPPER", "pepper-test-gate-desde-el-panel-nunca-produccion")

    (tmp_path / "primera").mkdir()
    documentos.escribir_pdf(tmp_path / "primera", "01-lab", documentos.texto_layout_no_reconocido())
    (tmp_path / "segunda").mkdir()
    documentos.escribir_pdf(tmp_path / "segunda", "01-lab", documentos.texto_layout_no_reconocido())

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

    estado_primera, _primera = _solicitar(
        aplicacion, "POST", "/corridas", json.dumps({"ruta": str(tmp_path / "primera")}).encode()
    )
    estado_segunda, segunda = _solicitar(
        aplicacion, "POST", "/corridas", json.dumps({"ruta": str(tmp_path / "segunda")}).encode()
    )

    assert estado_primera == "202 Accepted"
    assert estado_segunda == "409 Conflict"
    assert segunda["codigo"] == "corrida_en_curso"

    servicio.esperar_despachos_en_curso(timeout=120)
