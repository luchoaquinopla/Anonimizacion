"""Centinela de carrera contra Postgres REAL (`pytest.mark.postgres`).

`tests/salida/destinos/test_postgres.py` ya prueba la misma carrera forzando
el `IntegrityError` real de la restricción de clave primaria mediante
monkeypatch de la lectura optimista -- determinístico, corre en la suite
normal contra SQLite, respeta el guardia de red de
`tests/conftest.py::_bloquear_llamadas_de_red_reales` (invariante deliberado:
el pipeline es 100% offline en tiempo de ejecución).

Esos tests NO prueban con dos conexiones GENUINAMENTE concurrentes: la
verificación manual contra Postgres real durante la implementación (dos
hilos, `docker-compose.yml`) confirmó que el código viejo revienta con
`psycopg.errors.UniqueViolation` sin capturar y que el nuevo resuelve la
carrera -- pero esa verificación vivía en un script de sesión, no en la
suite. Este archivo la deja como centinela permanente, sin romper el
invariante offline por defecto:

- Marcado `pytest.mark.postgres` (registrado en `pyproject.toml`): se puede
  correr solo con `pytest -m postgres` o excluir con `pytest -m "not postgres"`.
- El fixture `engine_postgres_real` intenta conectar y usa `pytest.skip(...)`
  si Postgres no responde -- así `pytest` sin filtros sigue siendo verde en
  una máquina sin Docker, y pasa a ejercitar la carrera real en cuanto
  `docker compose up -d postgres` está arriba (ver `docker-compose.yml`).
- Restaura `socket.socket.connect` a la implementación real SÓLO para este
  fixture, con el mismo patrón que
  `tests/scripts/test_servir_panel.py::_CONNECT_REAL` (capturado a nivel de
  módulo, antes de que el guardia de sesión lo parchee).

Método de la carrera: dos hilos, cada uno con su PROPIA `Session`/conexión
real del pool, sincronizados con una `threading.Barrier` para forzar que
AMBOS hayan terminado su lectura optimista (`_buscar_vinculo`/
`_buscar_episodio`) antes de que cualquiera intente el `INSERT` -- el mismo
timing que dos procesos de `ProcessPoolExecutor` (PR 3) verían resolviendo
el mismo paciente o escribiendo el mismo episodio a la vez. La barrera
controla el TIMING, no el resultado: el `INSERT` y el `IntegrityError`
resultante son reales.

Gotcha encontrado escribiendo este archivo (documentado para no repetirlo):
el wrapper que agrega la espera de la barrera NO puede capturar `original =
escritor._buscar_vinculo` DENTRO de la función de cada hilo -- `_buscar_vinculo`
es un atributo de INSTANCIA compartido entre los dos hilos (mismo `escritor`),
así que hay una carrera real sobre ESE atributo: si el hilo B lee `original`
después de que el hilo A ya lo pisó con SU wrapper, el wrapper de B queda
envolviendo al wrapper de A en vez del método real -- resultado: invocaciones
duplicadas y un tercer `barrier.wait()` que nadie empareja, `BrokenBarrierError`
por timeout. La solución es capturar el método real UNA sola vez desde la
CLASE (`EscritorPostgres._buscar_vinculo`, un `@staticmethod`, no cambia con
el estado de ninguna instancia) ANTES de lanzar los hilos.
"""
from __future__ import annotations

import socket
import threading
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.salida.destinos.postgres import EscritorPostgres, construir_engine_postgres
from anonimizacion.salida.modelos_orm import Base, Episodio, VinculoPaciente

# Ver el docstring del módulo: capturado ANTES de que
# `tests/conftest.py::_bloquear_llamadas_de_red_reales` (autouse, scope de
# sesión) parchee `socket.socket.connect` para toda la suite.
_CONNECT_REAL = socket.socket.connect

_URL_POSTGRES_REAL = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"

pytestmark = pytest.mark.postgres


@pytest.fixture()
def engine_postgres_real(monkeypatch):
    """Motor contra el Postgres real de `docker-compose.yml`, o `skip` si no responde.

    La prueba de conectividad usa `connect_timeout=3` explícito -- sin esto,
    un puerto de Docker detenido (el mapeo queda "abierto" a nivel de SO
    aunque el contenedor esté parado, al menos en Windows) NO rechaza la
    conexión de inmediato: se cuelga hasta el timeout por defecto del driver
    (mucho más de 3 s), y ESO es justo lo que este fixture tiene que evitar
    para no romper (ni demorar de más) una corrida de `pytest` sin Docker
    levantado. El engine real que usan los tests se arma después, sin este
    override, vía `construir_engine_postgres` (mismo camino que producción).
    """
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    sonda = sa.create_engine(_URL_POSTGRES_REAL, connect_args={"connect_timeout": 3})
    try:
        with sonda.connect():
            pass
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexión es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_REAL}: {excepcion}")
    finally:
        sonda.dispose()

    engine = construir_engine_postgres(_URL_POSTGRES_REAL)

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_registrar_vinculo_resiste_una_carrera_real_con_homonimo(engine_postgres_real: sa.Engine) -> None:
    """Dos hilos, dos conexiones reales: homónimo real (`id_paciente` distinto)
    bajo carrera genuina -- el invariante "una vez ambiguo, siempre ambiguo"
    tiene que sobrevivir sin propagar ninguna excepción."""
    escritor = EscritorPostgres(engine_postgres_real)
    id_alt = "alt-integracion-postgres-real"
    barrera = threading.Barrier(2)
    resultados: list[tuple[str, Exception | None]] = [("pendiente", None), ("pendiente", None)]
    # Capturado UNA vez, vía la CLASE, antes de lanzar los hilos -- ver el
    # docstring del módulo para el porqué (gotcha real encontrado acá).
    original_buscar_vinculo = EscritorPostgres._buscar_vinculo

    def _tarea(indice: int, id_paciente: str) -> None:
        def _buscar_y_esperar(sesion, id_alt_paciente):
            resultado = original_buscar_vinculo(sesion, id_alt_paciente)
            barrera.wait(timeout=10)  # fuerza que AMBOS hilos ya leyeron antes de que cualquiera inserte
            return resultado

        escritor._buscar_vinculo = _buscar_y_esperar
        try:
            escritor.registrar_vinculo(id_alt, id_paciente)
            resultados[indice] = ("ok", None)
        except Exception as excepcion:  # noqa: BLE001 -- se reporta en el assert, no se traga
            resultados[indice] = ("error", excepcion)

    hilos = [
        threading.Thread(target=_tarea, args=(0, "pid-real-A")),
        threading.Thread(target=_tarea, args=(1, "pid-real-B")),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert all(estado == "ok" for estado, _ in resultados), resultados

    with Session(engine_postgres_real) as sesion:
        fila = sesion.get(VinculoPaciente, id_alt)
    assert fila is not None
    assert fila.id_paciente is None
    assert fila.ambiguo is True


def test_escribir_episodio_resiste_una_carrera_real(engine_postgres_real: sa.Engine) -> None:
    """Dos hilos, dos conexiones reales, mismo `id_episodio`: no debe quedar
    ninguna fila duplicada ni ninguna excepción sin capturar."""
    escritor = EscritorPostgres(engine_postgres_real)
    id_episodio = "ep-integracion-postgres-real"
    barrera = threading.Barrier(2)
    resultados: list[tuple[str, Exception | None]] = [("pendiente", None), ("pendiente", None)]
    # Capturado UNA vez, vía la CLASE -- mismo motivo que en el test de arriba.
    original_buscar_episodio = EscritorPostgres._buscar_episodio

    def _tarea(indice: int) -> None:
        def _buscar_y_esperar(sesion, id_episodio_buscado):
            resultado = original_buscar_episodio(sesion, id_episodio_buscado)
            barrera.wait(timeout=10)
            return resultado

        escritor._buscar_episodio = _buscar_y_esperar
        try:
            escritor.escribir_episodio(id_episodio=id_episodio, id_paciente="pid-real-1", fecha_ancla=date(2024, 1, 10))
            resultados[indice] = ("ok", None)
        except Exception as excepcion:  # noqa: BLE001
            resultados[indice] = ("error", excepcion)

    hilos = [threading.Thread(target=_tarea, args=(i,)) for i in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert all(estado == "ok" for estado, _ in resultados), resultados

    with Session(engine_postgres_real) as sesion:
        filas = sesion.query(Episodio).all()
    assert len(filas) == 1
