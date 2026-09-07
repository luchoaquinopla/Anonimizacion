"""Tests de `scripts/servir_panel.py` (tasks.md 10.10-10.11).

Confirma que el punto de entrada levanta un `wsgiref.simple_server` real con
`socketserver.ThreadingMixIn` (design.md, "El punto de entrada") y responde
a una petición HTTP real -- no un doble de la aplicación WSGI.
"""

from __future__ import annotations

import importlib.util
import socket
import socketserver
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.corridas import Corrida
from anonimizacion.dominio.estados_corrida import EstadoCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base, CorridaOrm, Estudio

# `tests/conftest.py::_bloquear_llamadas_de_red_reales` parchea
# `socket.socket.connect` para TODA la sesión, antes de que corra ningún
# test -- pero DESPUÉS de que este módulo se importa (la colección de
# pytest ocurre antes del setup de fixtures de sesión). Se captura acá la
# implementación real mientras todavía está intacta, para poder restaurarla
# sólo en el único test de este archivo que necesita una conexión de
# loopback real: ese guardia protege que el PIPELINE sea offline (spec
# `pii-detection`), no que este servidor de desarrollo pueda probarse contra
# sí mismo por loopback.
#
# Esto depende del ORDEN DE IMPORT, y es frágil por eso (auditado en la
# revisión de seguridad de este cambio): si en el futuro otro `conftest.py`
# también parchea `socket.socket.connect` a nivel de módulo, y ese parche
# corre ANTES de que ESTE módulo se importe, `_CONNECT_REAL` capturaría la
# versión YA parcheada -- este test seguiría pasando, pero creyendo que usa
# un socket real cuando en realidad seguiría bloqueado (falso verde
# silencioso). No se corrige acá porque hoy no hay ningún otro parche de
# `connect` en el árbol de conftests y cambiarlo es una decisión de alcance
# mayor. La alternativa más robusta, para cuando haga falta: un fixture
# dedicado (p.ej. `sin_guardia_de_red`) que el guardia de sesión reconozca
# por un marcador explícito de pytest (`@pytest.mark.red_real`) y salga sin
# aplicar el parche para ese test puntual, en vez de depender de qué módulo
# se importó primero.
_CONNECT_REAL = socket.socket.connect

_RUTA_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "servir_panel.py"


def _cargar_script():
    """Carga `scripts/servir_panel.py` por ruta -- `scripts/` no es un paquete instalado."""
    spec = importlib.util.spec_from_file_location("_servir_panel_bajo_prueba", _RUTA_SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_parsear_args_expone_procesos_con_default_conservador(monkeypatch) -> None:
    """Feature `despachador-desde-el-panel`: mismo flag que `--procesos` en
    `scripts/procesar_carpeta.py`, mismo default (`despacho_paralelo.grado_de_concurrencia_por_defecto`)
    -- el despachador desde el panel usa el mismo grado de concurrencia que
    el script."""
    from anonimizacion.trabajadores import despacho_paralelo

    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py"])

    args = modulo._parsear_args()

    assert args.procesos == despacho_paralelo.grado_de_concurrencia_por_defecto()


def test_parsear_args_rechaza_procesos_por_encima_del_tope_duro(monkeypatch) -> None:
    from anonimizacion.trabajadores import despacho_paralelo

    modulo = _cargar_script()
    tope = despacho_paralelo.tope_duro_concurrencia()
    monkeypatch.setattr("sys.argv", ["servir_panel.py", "--procesos", str(tope + 1)])

    with pytest.raises(SystemExit):
        modulo._parsear_args()


def test_main_verifica_el_pepper_antes_de_conectar_a_postgres(monkeypatch) -> None:
    """Decisión "el pepper HMAC" (feature `despachador-desde-el-panel`): sin
    `ANONIMIZACION_PEPPER`/`ANONIMIZACION_PEPPER_ARCHIVO`, cada proceso hijo
    fallaría recién al arrancar (`despacho_paralelo.inicializar_trabajador`
    -> `obtener_pepper()`), a mitad de una corrida ya aceptada -- el fallo
    quedaría disfrazado de `PROCESO_INTERRUMPIDO` en cuarentena, ocultando la
    causa real (una variable de entorno faltante en el SERVIDOR, no en el
    documento). El servidor tiene que fallar temprano y claro, ANTES de
    conectar a Postgres o de aceptar ningún `POST /corridas`."""
    from anonimizacion.pseudonimizacion.almacen_pepper import ErrorPepperNoConfigurado

    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: (_ for _ in ()).throw(ErrorPepperNoConfigurado()))

    llamadas: list[str] = []
    monkeypatch.setattr(
        modulo, "construir_engine_postgres", lambda url: llamadas.append(url) or sa.create_engine("sqlite://")
    )

    codigo = modulo.main()

    assert codigo == 1
    assert llamadas == [], "no debe conectar a Postgres si el pepper no esta configurado"


def test_keyboardinterrupt_pide_apagado_cooperativo_antes_de_cerrar(monkeypatch) -> None:
    """Revisión adversarial crítico 2: `daemon=True` en el hilo de despacho
    NO alcanza -- `ProcessPoolExecutor` registra su propio `atexit` que
    espera a que el pool activo termine, sin importar que el hilo dueño sea
    daemon (medido: ~8 s de proceso colgado con un hilo daemon de 8 s de
    trabajo, y dos procesos hijos huérfanos al matar el padre a la fuerza).

    El apagado real es cooperativo: `main()` tiene que llamar
    `servicio.solicitar_apagado()` ANTES de `esperar_despachos_en_curso`
    (para que el despacho tenga la señal antes de que alguien se quede
    esperando), avisar al operador en castellano llano, y sólo entonces
    cerrar el servidor -- nunca matar procesos hijos a la fuerza."""
    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: b"pepper-wiring-nunca-real")
    monkeypatch.setattr(
        modulo, "construir_engine_postgres", lambda url: sa.create_engine("sqlite:///:memory:"), raising=False
    )

    llamadas: list[str] = []

    class _ServicioEspia:
        def solicitar_apagado(self) -> None:
            llamadas.append("solicitar_apagado")

        def esperar_despachos_en_curso(self, timeout=None) -> None:
            llamadas.append(f"esperar_despachos_en_curso(timeout={timeout})")

        def hay_despachos_en_curso(self) -> bool:
            llamadas.append("hay_despachos_en_curso")
            return False

    servicio_espia = _ServicioEspia()
    monkeypatch.setattr(
        modulo,
        "construir_aplicacion",
        lambda *args, **kwargs: (lambda entorno, iniciar: [b""], servicio_espia),
    )

    class _ServidorFalso:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt()

        def server_close(self) -> None:
            llamadas.append("server_close")

    monkeypatch.setattr(modulo, "make_server", lambda *args, **kwargs: _ServidorFalso())

    codigo = modulo.main()

    assert codigo == 0
    # Orden: pedir apagado ANTES de esperar, y cerrar el servidor AL FINAL --
    # nunca al revés (cerrar el servidor mientras un despacho sigue en vuelo
    # dejaría esa corrida sin que nadie la haya avisado).
    assert llamadas == [
        "solicitar_apagado",
        f"esperar_despachos_en_curso(timeout={modulo._TIMEOUT_APAGADO_SEG})",
        "hay_despachos_en_curso",
        "server_close",
    ]


def test_el_servidor_es_wsgiref_con_threading_mixin() -> None:
    """10.10: el punto de entrada usa `wsgiref.simple_server` + `ThreadingMixIn`."""
    modulo = _cargar_script()

    assert issubclass(modulo._ServidorConHilos, socketserver.ThreadingMixIn)
    assert issubclass(modulo._ServidorConHilos, WSGIServer)


def test_por_defecto_escucha_solo_en_localhost() -> None:
    """Hallazgo de seguridad: `make_server("", ...)` equivale a `0.0.0.0` --
    el panel (datos operativos sin autenticación, sin TLS) quedaría expuesto
    a toda la red del instituto por defecto. El default correcto es
    `127.0.0.1`; exponerlo a la red exige `--escuchar-red` a propósito.
    """
    modulo = _cargar_script()

    assert modulo._resolver_host(escuchar_red=False) == "127.0.0.1"
    assert modulo._resolver_host(escuchar_red=True) == ""


def test_el_flag_escuchar_red_es_explicito_y_apagado_por_defecto(monkeypatch) -> None:
    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py"])

    args = modulo._parsear_args()

    assert args.escuchar_red is False


def test_main_usa_construir_engine_postgres_no_create_engine_pelado(monkeypatch) -> None:
    """openspec `paralelismo-de-procesamiento` PR 1: `main()` llamaba
    `sa.create_engine(args.db_url)` pelado -- ver
    `postgres.py::construir_engine_postgres` para el porqué eso importa
    contra un panel de larga vida hablando con RDS."""
    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: b"pepper-wiring-nunca-real")

    llamadas: list[str] = []

    def _engine_espia(url: str) -> sa.Engine:
        llamadas.append(url)
        return sa.create_engine("sqlite:///:memory:")

    monkeypatch.setattr(modulo, "construir_engine_postgres", _engine_espia, raising=False)

    class _ServidorFalso:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt()

        def server_close(self) -> None:
            pass

    monkeypatch.setattr(modulo, "make_server", lambda *args, **kwargs: _ServidorFalso())

    codigo = modulo.main()

    assert codigo == 0
    assert llamadas == [modulo._DB_URL_DEFAULT]


def test_construir_aplicacion_recupera_corridas_abandonadas_al_arrancar(tmp_path, capsys) -> None:
    """Decisión "qué pasa si el servidor se cae con una corrida en curso"
    (feature `despachador-desde-el-panel`): al construir la aplicación --
    UNA vez, antes de servir ninguna petición -- toda corrida no terminal
    tiene que cerrarse `FALLIDA`. Sin esto, tras cualquier caída el gate de
    "una corrida a la vez" (`ServicioCorridasReal.crear_corrida`) queda
    bloqueado para siempre: la corrida fantasma nunca termina, así que ningún
    `POST /corridas` nuevo puede aceptarse."""
    modulo = _cargar_script()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    repositorio = RepositorioCorridas(engine)
    abandonada = Corrida.crear("corrida-abandonada")
    repositorio.crear_corrida(abandonada)
    abandonada.avanzar_a(EstadoCorrida.INVENTARIANDO)
    repositorio.actualizar_corrida(abandonada, version_esperada=0)

    # `ahora` bien en el futuro (revisión adversarial crítico 1): sin esto,
    # `corrida.actualizada_en` (recién escrita arriba) siempre estaría dentro
    # de CUALQUIER margen de inactividad razonable -- ver
    # `lanzador_corrida.recuperar_corridas_abandonadas`.
    mucho_despues = datetime.now(timezone.utc) + timedelta(days=1)
    modulo.construir_aplicacion(engine, tmp_path, db_url="sqlite://", procesos=1, ahora=mucho_despues)

    with Session(engine) as sesion:
        fila = sesion.get(CorridaOrm, "corrida-abandonada")
    assert fila.estado == "fallida"
    assert "corrida-abandonada" in capsys.readouterr().err


def test_el_servidor_real_responde_una_peticion_http_real(tmp_path, monkeypatch) -> None:
    """10.10/10.11: levanta el servidor en un hilo y le hace una petición HTTP real."""
    # Ver el comentario junto a `_CONNECT_REAL`: este es el único test que
    # necesita loopback real, para probar el servidor real de punta a punta.
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)

    modulo = _cargar_script()

    # `StaticPool` + `check_same_thread=False`: el servidor real atiende cada
    # solicitud en un hilo propio (`_ServidorConHilos`), y el pool por hilo
    # que SQLAlchemy usa por defecto para `sqlite://` le daría a ese hilo una
    # base en memoria distinta y vacía -- de ahí "no such table" si no se fija
    # esto. No es una condición del código bajo prueba, es del fixture.
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)
    corrida_id = "corrida-servidor-real"
    RepositorioCorridas(engine).crear_corrida(Corrida.crear(corrida_id))
    with Session(engine) as sesion, sesion.begin():
        from datetime import date

        sesion.add(
            Estudio(
                id_episodio="ep-1",
                tipo_documento="laboratorio",
                fecha_estudio=date(2026, 1, 1),
                precision_hora="ausente",
                clave_documento="clave-servidor-real",
                corrida_id=corrida_id,
            )
        )

    aplicacion, _servicio = modulo.construir_aplicacion(engine, tmp_path, db_url="sqlite://", procesos=1)
    servidor = make_server("127.0.0.1", 0, aplicacion, server_class=modulo._ServidorConHilos)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/panel/{corrida_id}", timeout=5) as respuesta:
            estado = respuesta.status
            cuerpo = respuesta.read().decode("utf-8")
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)

    assert estado == 200
    assert corrida_id in cuerpo
    assert 'id="valor-publicados">1' in cuerpo
