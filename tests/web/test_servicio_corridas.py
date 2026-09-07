"""Tests de `ServicioCorridasReal` (tasks.md 9.4/9.5/9.8/9.9): implementación real, no un doble.

Antes de esto, `ServicioCorridas` sólo existía como `Protocol` y `_ServicioFake`
en `tests/web/test_rutas_corridas.py`. La spec `portal-de-corridas` (delta)
exige que crear/consultar tenga efecto sobre datos reales -- este módulo lo
verifica con un `LanzadorCorrida` real contra SQLite en memoria, no con otro
doble.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa

from anonimizacion.dominio.errores import ErrorDocumento
from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.web.servicio_corridas import CorridaEnCursoError, ServicioCorridasReal, construir_payload_embudo

_DB_URL_NUNCA_REAL = "postgresql+psycopg://no-se-conecta-en-estos-tests/db"


@dataclass
class _CuarentenaFake:
    registrados: list[ErrorDocumento] = field(default_factory=list)

    def registrar(self, error: ErrorDocumento) -> None:
        self.registrados.append(error)


def _motor_con_esquema(tmp_path) -> sa.Engine:
    """SQLite de ARCHIVO (no `:memory:`), una conexión real POR HILO -- no
    `StaticPool` (una única conexión compartida) -- feature
    `despachador-desde-el-panel`.

    `crear_corrida` arranca su despacho en un hilo de FONDO y sigue leyendo
    en el hilo PRINCIPAL casi al mismo tiempo (`consultar_corrida`, para
    armar su propio retorno): dos hilos tocando la MISMA conexión cruda de
    `sqlite3` a la vez (lo que hace `StaticPool` + `check_same_thread=False`)
    no es seguro -- se probó con `StaticPool` en esta sesión y produjo una
    corrida flaky, intermitente entre "completada" y "procesando" según qué
    hilo ganara la carrera sobre la conexión compartida. Un archivo real con
    `timeout` (espera si la base está bloqueada en vez de fallar al toque) le
    da a cada hilo su PROPIA conexión -- mucho más parecido a
    `construir_engine_postgres` en producción (pool real, una conexión por
    conexión lógica) que una única conexión en memoria repartida a mano.
    """
    ruta = tmp_path / "_prueba_servicio_corridas.sqlite3"
    motor = sa.create_engine(f"sqlite:///{ruta}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(motor)
    return motor


@dataclass
class _DespachadorFake:
    """Doble del despachador REAL (`despacho_paralelo.despachar_en_paralelo`)
    para tests que verifican `crear_corrida`/el gate, no el despacho en sí
    mismo -- ese camino tiene su propio test end-to-end con el despachador
    real, ver `tests/web/test_despacho_real_desde_el_panel.py`. Drena
    `grupos` (como haría el real) y devuelve un resultado fijo, sin tocar
    Postgres ni `ProcessPoolExecutor`.

    `llamadas` registra los kwargs de cada invocación -- permite verificar
    el CABLEADO (qué se le pasó al despachador) sin ejecutar nada real.
    """

    resultados: list[dict[str, object]] = field(default_factory=list)
    llamadas: list[dict[str, object]] = field(default_factory=list)

    def __call__(self, *, corrida_id, grupos, crear_pool, procesos, cuarentena, **_kwargs):
        grupos_consumidos = list(grupos)
        self.llamadas.append(
            {
                "corrida_id": corrida_id,
                "grupos": grupos_consumidos,
                "procesos": procesos,
                "cuarentena": cuarentena,
            }
        )
        total_documentos = sum(len(grupo) for grupo in grupos_consumidos)
        return list(self.resultados), total_documentos, len(grupos_consumidos)


def test_crear_corrida_delega_en_el_lanzador_real(tmp_path) -> None:
    """9.4: falla porque hoy `crear_corrida` es un doble que no toca ninguna base."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    despachador = _DespachadorFake()
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=despachador
    )

    estado = servicio.crear_corrida(str(tmp_path))
    servicio.esperar_despachos_en_curso()

    assert estado.id_corrida
    # `estado` es una FOTO tomada apenas se lanza el despacho en segundo plano
    # (feature `despachador-desde-el-panel`): con un despachador de verdad
    # (horas) siempre se ve `inventariando`, pero con este DOBLE trivial (que
    # ni siquiera toca Postgres) el hilo de fondo puede terminar ANTES de que
    # el hilo principal llegue a leer esta foto -- afirmar un valor puntual
    # acá sería una carrera de la PRUEBA, no del código bajo prueba. Lo
    # determinístico, y lo que importa, es el estado FINAL tras
    # `esperar_despachos_en_curso`: `completada` -- el despachador real ya no
    # queda fuera de alcance.
    assert estado.estado in {"inventariando", "procesando", "completada"}
    from anonimizacion.web import embudo_corrida

    embudo_corrida._CACHE.clear()  # bypasea la memoización de 1s -- ver el test de abajo
    consultada_al_final = servicio.consultar_corrida(estado.id_corrida)
    assert consultada_al_final.estado == "completada"
    (llamada,) = despachador.llamadas
    assert llamada["corrida_id"] == estado.id_corrida
    assert sum(len(grupo) for grupo in llamada["grupos"]) == 1


def test_consultar_corrida_refleja_el_estado_real_no_un_valor_fijo(tmp_path) -> None:
    """Requisito agregado de `portal-de-corridas`: consultar una corrida real
    refleja su estado real, no un valor fijo de prueba."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    (tmp_path / "dos.pdf").write_bytes(b"contenido-dos")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=_DespachadorFake()
    )

    creada = servicio.crear_corrida(str(tmp_path))
    servicio.esperar_despachos_en_curso()
    # `crear_corrida` ya llamó `consultar_corrida` internamente para armar su
    # propio retorno, ANTES de que el despacho de fondo terminara -- esa
    # lectura quedó memoizada 1 s (`embudo_corrida._CACHE`, design.md "Plan de
    # acceso"). Bypasearla acá es lo mismo que ya hacen
    # `tests/web/test_embudo_corrida.py`/`tests/integracion/test_embudo_corrida_integracion.py`
    # para leer el estado post-despacho sin esperar el TTL.
    from anonimizacion.web import embudo_corrida

    embudo_corrida._CACHE.clear()
    consultada = servicio.consultar_corrida(creada.id_corrida)

    assert consultada.id_corrida == creada.id_corrida
    # 2 documentos inventariados, 0 publicados, 0 apartados -> residuo = 2.
    assert consultada.documentos_pendientes == 2
    assert consultada.cuarentenas == 0
    assert consultada.estado == "completada"


def test_crear_corrida_rechaza_una_segunda_mientras_la_primera_sigue_activa(tmp_path) -> None:
    """Decisión "dos corridas a la vez": el gate rechaza un `POST /corridas`
    nuevo mientras cualquier otra corrida siga en un estado no terminal --
    `despachar_en_paralelo` ya reserva su propio presupuesto de memoria
    (~875 MB medidos por proceso, `despacho_paralelo.py`) y dos corridas
    concurrentes lo duplicarían sin que nada lo repartiera. No lanza ningún
    hilo de despacho: el gate corta ANTES de tocar `LanzadorCorrida.lanzar`."""
    (tmp_path / "activa").mkdir()
    (tmp_path / "activa" / "uno.pdf").write_bytes(b"contenido-uno")
    (tmp_path / "nueva").mkdir()
    (tmp_path / "nueva" / "dos.pdf").write_bytes(b"contenido-dos")

    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    # Corrida activa creada DIRECTO con el lanzador (sin pasar por el
    # servicio, para no depender del despacho en este test): queda en
    # INVENTARIANDO, un estado no terminal.
    activa = lanzador.lanzar(tmp_path / "activa")
    list(activa.referencias)

    despachador = _DespachadorFake()
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=despachador
    )

    with pytest.raises(CorridaEnCursoError) as excinfo:
        servicio.crear_corrida(str(tmp_path / "nueva"))

    assert excinfo.value.id_corrida_activa == activa.corrida_id
    assert despachador.llamadas == [], "el gate corta antes de despachar nada"


def test_crear_corrida_sin_pdfs_no_lanza_ningun_despacho(tmp_path) -> None:
    """Paridad con `scripts/procesar_carpeta.py::ejecutar`: una carpeta sin
    PDFs no dispara ningún hilo de despacho -- no hay nada que procesar."""
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    despachador = _DespachadorFake()
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=despachador
    )

    servicio.crear_corrida(str(tmp_path))
    servicio.esperar_despachos_en_curso()

    assert despachador.llamadas == []


def test_crear_corrida_con_cuarentena_cierra_completada_con_cuarentena(tmp_path) -> None:
    """El despachador informa `hubo_cuarentena` a partir de los resultados
    reales -- `ServicioCorridasReal` no vuelve a consultar el embudo para
    decidir el estado final, usa lo que el despacho ya sabe."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    despachador = _DespachadorFake(resultados=[{"id_documento": "d1", "estado": "cuarentena"}])
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=despachador
    )

    creada = servicio.crear_corrida(str(tmp_path))
    servicio.esperar_despachos_en_curso()

    assert servicio.consultar_corrida(creada.id_corrida).estado == "completada_con_cuarentena"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_crear_corrida_si_el_despacho_explota_cierra_fallida(tmp_path) -> None:
    """Backstop (decisión "qué pasa si el servidor se cae"): una excepción
    INESPERADA que rompe el hilo de despacho entero no puede dejar la
    corrida diciendo `procesando` para siempre."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())

    def _despachador_que_explota(**_kwargs):
        raise RuntimeError("fallo inesperado simulado")

    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=_despachador_que_explota
    )

    creada = servicio.crear_corrida(str(tmp_path))
    servicio.esperar_despachos_en_curso()

    assert servicio.consultar_corrida(creada.id_corrida).estado == "fallida"


def test_el_json_del_embudo_informa_el_estado_real_de_una_corrida_lanzada(tmp_path) -> None:
    """El campo `estado` del contrato JSON no puede mentir `creada` para
    siempre: una corrida recién lanzada llegó a INVENTARIANDO (no más -- ver
    `fix/silencios-de-ingesta-y-panel`: `lanzar()` no procesa nada), y eso
    tiene que verse en `GET /corridas/{id}/embudo` (`construir_payload_embudo`)."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)
    payload = construir_payload_embudo(motor, resultado.corrida_id)

    assert payload is not None
    assert payload["estado"] == "inventariando"


def test_reintentar_corrida_lanza_notimplementederror(tmp_path) -> None:
    """9.8/9.9: la ruta traduce esto a 501, no a un 202 falso."""
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    servicio = ServicioCorridasReal(lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1)

    with pytest.raises(NotImplementedError):
        servicio.reintentar_corrida("cualquier-id")
