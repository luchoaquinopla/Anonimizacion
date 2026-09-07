"""Tests de `ServicioCorridasReal` (tasks.md 9.4/9.5/9.8/9.9): implementación real, no un doble.

Antes de esto, `ServicioCorridas` sólo existía como `Protocol` y `_ServicioFake`
en `tests/web/test_rutas_corridas.py`. La spec `portal-de-corridas` (delta)
exige que crear/consultar tenga efecto sobre datos reales -- este módulo lo
verifica con un `LanzadorCorrida` real contra SQLite en memoria, no con otro
doble.
"""

from __future__ import annotations

import threading
import time
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

    def __call__(self, *, corrida_id, grupos, crear_pool, procesos, cuarentena, detener=None, **_kwargs):
        grupos_consumidos = list(grupos)
        self.llamadas.append(
            {
                "corrida_id": corrida_id,
                "grupos": grupos_consumidos,
                "procesos": procesos,
                "cuarentena": cuarentena,
                "detener": detener,
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


# --- apagado ordenado (revisión adversarial crítico 2) -----------------------


def test_crear_corrida_le_pasa_al_despachador_el_evento_de_apagado_del_servicio(tmp_path) -> None:
    """`main()` (`scripts/servir_panel.py`) necesita poder pedirle a UN
    servicio que frene TODOS sus despachos en curso -- el mismo
    `threading.Event` tiene que viajar hasta el despachador real en cada
    corrida que este servicio lance."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    despachador = _DespachadorFake()
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=despachador
    )

    servicio.crear_corrida(str(tmp_path))
    servicio.esperar_despachos_en_curso()

    (llamada,) = despachador.llamadas
    assert llamada["detener"] is servicio._evento_apagado


def test_solicitar_apagado_marca_fallida_una_corrida_cuyo_despacho_se_corto(tmp_path) -> None:
    """Revisión adversarial crítico 2: si el despacho se corta porque se
    pidió apagado (Ctrl+C, `solicitar_apagado`), la corrida NO puede quedar
    diciendo `completada` -- no hay evidencia de que el inventario completo
    se haya procesado. Se cierra `FALLIDA`, la misma honestidad que ya exige
    un crash inesperado."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())

    def _despachador_cancelado_a_mitad_de_camino(*, detener, **_kwargs):
        detener.set()  # simula que Ctrl+C llegó DURANTE el despacho
        return [], 0, 0

    servicio = ServicioCorridasReal(
        lanzador=lanzador,
        motor=motor,
        db_url=_DB_URL_NUNCA_REAL,
        procesos=1,
        despachador=_despachador_cancelado_a_mitad_de_camino,
    )

    creada = servicio.crear_corrida(str(tmp_path))
    servicio.esperar_despachos_en_curso()

    assert servicio.consultar_corrida(creada.id_corrida).estado == "fallida"


def test_solicitar_apagado_es_idempotente_y_no_rompe_si_no_hay_despachos(tmp_path) -> None:
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    servicio = ServicioCorridasReal(lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1)

    servicio.solicitar_apagado()
    servicio.solicitar_apagado()

    assert servicio._evento_apagado.is_set()


# --- ventana TOCTOU del gate (revisión adversarial IMPORTANTE) --------------


def test_crear_corrida_con_dos_peticiones_concurrentes_una_sola_pasa_el_gate(tmp_path, monkeypatch) -> None:
    """Revisión adversarial: la ventana entre "leer si hay una corrida
    activa" y "crear la corrida" es real, no teórica -- reproducida con dos
    hilos REALES sincronizados con un `Barrier` (no en secuencia dentro del
    mismo hilo, que nunca ejercita la concurrencia real), y con un `sleep`
    corto insertado a propósito en el chequeo para ensanchar la ventana de
    forma determinística -- la misma ventana que en producción abre 0,5 s de
    latencia real (un `FuenteLocal` listando un directorio grande, un doble
    clic, un reintento del navegador).

    Con dos corridas concurrentes duplicando el presupuesto de memoria que
    el gate existe para proteger, exactamente UNA de las dos peticiones
    tiene que pasar."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "uno.pdf").write_bytes(b"contenido-a")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "uno.pdf").write_bytes(b"contenido-b")

    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())
    servicio = ServicioCorridasReal(
        lanzador=lanzador, motor=motor, db_url=_DB_URL_NUNCA_REAL, procesos=1, despachador=_DespachadorFake()
    )

    original_listar = RepositorioCorridas.listar_corridas_no_terminales

    def _listar_ensanchando_la_ventana(self):
        resultado = original_listar(self)
        time.sleep(0.2)  # ensancha la ventana TOCTOU a propósito, sólo para este test
        return resultado

    monkeypatch.setattr(RepositorioCorridas, "listar_corridas_no_terminales", _listar_ensanchando_la_ventana)

    barrera = threading.Barrier(2)
    resultados: dict[str, tuple[str, str]] = {}

    def _crear(etiqueta: str, ruta) -> None:
        barrera.wait()
        try:
            estado = servicio.crear_corrida(str(ruta))
            resultados[etiqueta] = ("OK", estado.id_corrida)
        except CorridaEnCursoError as error:
            resultados[etiqueta] = ("RECHAZADA", error.id_corrida_activa)

    hilo_a = threading.Thread(target=_crear, args=("A", tmp_path / "a"))
    hilo_b = threading.Thread(target=_crear, args=("B", tmp_path / "b"))
    hilo_a.start()
    hilo_b.start()
    hilo_a.join(timeout=10)
    hilo_b.join(timeout=10)

    print("Resultados:", resultados)
    exitosas = [valor for valor in resultados.values() if valor[0] == "OK"]
    rechazadas = [valor for valor in resultados.values() if valor[0] == "RECHAZADA"]
    assert len(exitosas) == 1, f"exactamente una de las dos peticiones tiene que pasar el gate: {resultados}"
    assert len(rechazadas) == 1, f"la otra tiene que ser rechazada: {resultados}"
    assert rechazadas[0][1] == exitosas[0][1], "la rechazada tiene que apuntar a la corrida que sí se creó"

    servicio.esperar_despachos_en_curso()


# --- latido periódico durante el despacho (revisión adversarial ronda 3) ----


def test_el_despacho_emite_latidos_periodicos_mientras_esta_en_curso(tmp_path) -> None:
    """Revisión adversarial ronda 3, hallazgo 2: un corpus PLANO agota todo
    el listado (hasheando cada archivo) antes de entregar su único grupo
    (`ingesta/fuente.py::listar_grupos`) -- con ~400.000 documentos eso puede
    tardar mucho más que el margen de inactividad, y en toda esa ventana no
    se escribe ningún `estudio`/`cuarentena`. `_despachar_y_cerrar` tiene que
    mantener `ultima_actividad` fresca durante TODO el despacho -- no sólo
    en `marcar_procesando` (al principio) y `marcar_finalizada` (al final) --
    con un latido propio, independiente de que ya se haya escrito un
    documento."""
    (tmp_path / "uno.pdf").write_bytes(b"contenido-uno")
    motor = _motor_con_esquema(tmp_path)
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())

    def _despachador_lento(**_kwargs):
        time.sleep(0.6)  # simula el hasheo largo de un corpus plano
        return [], 0, 0

    servicio = ServicioCorridasReal(
        lanzador=lanzador,
        motor=motor,
        db_url=_DB_URL_NUNCA_REAL,
        procesos=1,
        despachador=_despachador_lento,
        latido_intervalo_seg=0.05,
    )

    creada = servicio.crear_corrida(str(tmp_path))
    # Deja asentar `marcar_procesando` (que también toca `actualizada_en`,
    # una sola vez, al principio) ANTES de tomar la primera lectura -- si no,
    # ese bump por sí solo -- sin ningún latido -- alcanzaría para que
    # `durante_el_despacho > antes_de_dormir` sea cierto por la razón
    # equivocada. Confirmado revirtiendo el fix: el test pasaba igual sin
    # ningún latido real, por esta misma carrera.
    time.sleep(0.15)
    antes_de_dormir = lanzador.repositorio.ultima_actividad(creada.id_corrida)
    time.sleep(0.3)  # deja pasar varios intervalos de latido MIENTRAS el despachador sigue "trabajando"
    durante_el_despacho = lanzador.repositorio.ultima_actividad(creada.id_corrida)
    servicio.esperar_despachos_en_curso()

    assert antes_de_dormir is not None
    assert durante_el_despacho is not None
    assert durante_el_despacho > antes_de_dormir, (
        "ultima_actividad tiene que avanzar DURANTE el despacho por el latido, "
        "no sólo por marcar_procesando al principio y marcar_finalizada al final"
    )
