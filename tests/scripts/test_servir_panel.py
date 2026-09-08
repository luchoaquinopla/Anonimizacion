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


class _ServicioEspia:
    """Espía de `ServicioCorridasReal` para los tests de `KeyboardInterrupt`
    de `main()` -- `hay_despachos_en_curso` configurable para simular tanto
    el camino feliz (apagado cooperativo alcanza) como el de escalada
    (se agota y hace falta terminar a la fuerza)."""

    def __init__(self, *, sigue_en_curso_tras_cooperativo: bool = False) -> None:
        self.llamadas: list[str] = []
        self._sigue_en_curso = sigue_en_curso_tras_cooperativo

    def solicitar_apagado(self) -> None:
        self.llamadas.append("solicitar_apagado")

    def esperar_despachos_en_curso(self, timeout=None) -> None:
        self.llamadas.append(f"esperar_despachos_en_curso(timeout={timeout})")

    def hay_despachos_en_curso(self) -> bool:
        self.llamadas.append("hay_despachos_en_curso")
        return self._sigue_en_curso

    def terminar_despachos_a_la_fuerza(self) -> int:
        self.llamadas.append("terminar_despachos_a_la_fuerza")
        self._sigue_en_curso = False  # simula que la terminacion forzada libero al hilo
        return 2


def _preparar_main_con_servicio_espia(monkeypatch: pytest.MonkeyPatch, servicio_espia, llamadas: list[str]):
    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: b"pepper-wiring-nunca-real")
    monkeypatch.setattr(
        modulo, "construir_engine_postgres", lambda url: sa.create_engine("sqlite:///:memory:"), raising=False
    )
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
    return modulo


def test_keyboardinterrupt_pide_apagado_cooperativo_antes_de_cerrar(monkeypatch) -> None:
    """Revisión adversarial crítico 2 (y corrección ronda 3, hallazgo 3):
    `daemon=True` en el hilo de despacho NO alcanza -- `ProcessPoolExecutor`
    registra su propio `atexit` que espera a que el pool activo termine, sin
    importar que el hilo dueño sea daemon.

    El apagado tiene DOS escalones: (1) cooperativo -- `main()` llama
    `servicio.solicitar_apagado()` ANTES de `esperar_despachos_en_curso`, y
    si el despacho drena solo dentro del timeout, listo, sin tocar ningún
    proceso hijo. Este test cubre el camino FELIZ (el cooperativo alcanza) --
    `terminar_despachos_a_la_fuerza` NUNCA se llama acá."""
    servicio_espia = _ServicioEspia(sigue_en_curso_tras_cooperativo=False)
    modulo = _preparar_main_con_servicio_espia(monkeypatch, servicio_espia, servicio_espia.llamadas)

    codigo = modulo.main()

    assert codigo == 0
    # Orden: pedir apagado ANTES de esperar, y cerrar el servidor AL FINAL --
    # nunca al revés (cerrar el servidor mientras un despacho sigue en vuelo
    # dejaría esa corrida sin que nadie la haya avisado). Sin escalada:
    # `terminar_despachos_a_la_fuerza` no aparece en la lista.
    assert servicio_espia.llamadas == [
        "solicitar_apagado",
        f"esperar_despachos_en_curso(timeout={modulo._TIMEOUT_APAGADO_SEG})",
        "hay_despachos_en_curso",
        "server_close",
    ]


def test_keyboardinterrupt_escala_a_terminacion_forzada_si_el_cooperativo_se_agota(monkeypatch) -> None:
    """Revisión adversarial ronda 3, hallazgo 3: "el resguardo del timeout es
    una ilusión" -- medido, con el apagado cooperativo agotado, el proceso
    quedaba colgado ~114 s de todos modos porque nada terminaba los workers.

    Segundo escalón: si `hay_despachos_en_curso()` sigue `True` después del
    apagado cooperativo, `main()` tiene que llamar
    `terminar_despachos_a_la_fuerza()` -- y avisar al operador, en
    castellano llano, que el trabajo en vuelo se perdió (no "puede tardar en
    salir de todos modos" sin decir qué se hace al respecto)."""
    servicio_espia = _ServicioEspia(sigue_en_curso_tras_cooperativo=True)
    modulo = _preparar_main_con_servicio_espia(monkeypatch, servicio_espia, servicio_espia.llamadas)

    codigo = modulo.main()

    assert codigo == 0
    assert servicio_espia.llamadas == [
        "solicitar_apagado",
        f"esperar_despachos_en_curso(timeout={modulo._TIMEOUT_APAGADO_SEG})",
        "hay_despachos_en_curso",
        "terminar_despachos_a_la_fuerza",
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


def test_construir_aplicacion_sin_secreto_no_exige_autenticacion(tmp_path) -> None:
    """Feature `acceso-al-panel`: `secreto=None` (default) preserva el
    comportamiento previo -- éste es el modo que usa el resto de los tests
    de este archivo que no pasan `secreto`, y no debe empezar a exigir
    autenticación por accidente."""
    modulo = _cargar_script()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)

    aplicacion, _servicio = modulo.construir_aplicacion(engine, tmp_path, db_url="sqlite://", procesos=1)

    estado: list[str] = []
    aplicacion(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/corridas/inexistente", "wsgi.input": None, "CONTENT_LENGTH": "0"},
        lambda codigo, headers: estado.append(codigo),
    )
    # sin Authorization y sin embargo NO 401: la ruta responde según su
    # propia lógica (acá 200, porque el servicio fake/real no valida
    # existencia en este wiring) -- lo que importa es que nunca es 401.
    assert estado[0] != "401 Unauthorized"


def test_construir_aplicacion_con_secreto_exige_autenticacion_en_toda_ruta(tmp_path) -> None:
    """Feature `acceso-al-panel`: pasar `secreto` envuelve la aplicación
    ENTERA con `autenticacion_panel.exigir_autenticacion` -- se prueba
    contra el WSGI real devuelto por `construir_aplicacion`, no contra un
    doble del enrutador (para no validar un cableado que producción no usa)."""
    modulo = _cargar_script()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    Base.metadata.create_all(engine)

    aplicacion, _servicio = modulo.construir_aplicacion(
        engine, tmp_path, db_url="sqlite://", procesos=1, secreto=b"secreto-de-test"
    )

    estado: list[str] = []
    encabezados: list[tuple[str, str]] = []
    cuerpo = aplicacion(
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/panel/x", "wsgi.input": None, "CONTENT_LENGTH": "0"},
        lambda codigo, headers: (estado.append(codigo), encabezados.extend(headers)),
    )

    assert estado[0] == "401 Unauthorized"
    assert dict(encabezados)["WWW-Authenticate"].startswith("Basic")
    assert b"secreto-de-test" not in b"".join(cuerpo)


def test_main_falla_temprano_si_escuchar_red_sin_secreto_configurado(monkeypatch) -> None:
    """Decisión "qué pasa si el secreto no está configurado" (feature
    `acceso-al-panel`): `--escuchar-red` expone el panel a toda la red del
    instituto -- arrancar así SIN autenticación configurada es exactamente
    el agujero que esta feature cierra, así que `main()` tiene que fallar
    ANTES de conectar a Postgres, igual que ya hace con el pepper."""
    from anonimizacion.web.secreto_panel import ErrorSecretoPanelNoConfigurado

    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py", "--escuchar-red"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: b"pepper-wiring-nunca-real")
    monkeypatch.setattr(
        modulo, "obtener_secreto_panel", lambda: (_ for _ in ()).throw(ErrorSecretoPanelNoConfigurado())
    )

    llamadas: list[str] = []
    monkeypatch.setattr(
        modulo, "construir_engine_postgres", lambda url: llamadas.append(url) or sa.create_engine("sqlite://")
    )

    codigo = modulo.main()

    assert codigo == 1
    assert llamadas == [], "no debe conectar a Postgres si --escuchar-red no tiene secreto configurado"


def test_main_falla_temprano_no_filtra_el_secreto_ni_rutas_del_sistema(monkeypatch, capsys) -> None:
    from anonimizacion.web.secreto_panel import ErrorSecretoPanelNoConfigurado

    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py", "--escuchar-red"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: b"pepper-wiring-nunca-real")
    monkeypatch.setattr(
        modulo, "obtener_secreto_panel", lambda: (_ for _ in ()).throw(ErrorSecretoPanelNoConfigurado())
    )
    monkeypatch.setattr(modulo, "construir_engine_postgres", lambda url: sa.create_engine("sqlite://"))

    modulo.main()

    salida_error = capsys.readouterr().err
    assert "ANONIMIZACION_PANEL_SECRETO" in salida_error  # el NOMBRE de la variable no es secreto
    assert "Traceback" not in salida_error


def test_main_sin_escuchar_red_y_sin_secreto_arranca_igual(monkeypatch) -> None:
    """Bar preexistente conservado (feature `acceso-al-panel`): sólo en
    `127.0.0.1` sigue tolerado sin autenticación, para no romper el uso
    local/de desarrollo que ya existía antes de este cambio."""
    from anonimizacion.web.secreto_panel import ErrorSecretoPanelNoConfigurado

    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["servir_panel.py"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: b"pepper-wiring-nunca-real")
    monkeypatch.setattr(
        modulo, "obtener_secreto_panel", lambda: (_ for _ in ()).throw(ErrorSecretoPanelNoConfigurado())
    )
    monkeypatch.setattr(
        modulo, "construir_engine_postgres", lambda url: sa.create_engine("sqlite:///:memory:"), raising=False
    )

    class _ServidorFalso:
        def serve_forever(self) -> None:
            raise KeyboardInterrupt()

        def server_close(self) -> None:
            pass

    monkeypatch.setattr(modulo, "make_server", lambda *args, **kwargs: _ServidorFalso())

    codigo = modulo.main()

    assert codigo == 0


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
