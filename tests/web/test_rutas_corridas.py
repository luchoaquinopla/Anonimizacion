from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.corridas import Corrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base, Estudio
from anonimizacion.web.rutas_corridas import EstadoCorridaPortal, crear_aplicacion_corridas
from anonimizacion.ingesta.lanzador_corrida import CorridaEnCursoError


@dataclass
class _ServicioFake:
    solicitudes: list[tuple[str, str]]

    def crear_corrida(self, ruta_autorizada: str) -> EstadoCorridaPortal:
        self.solicitudes.append(("crear", ruta_autorizada))
        return EstadoCorridaPortal("corrida-1", "creada", 0, 0)

    def consultar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
        self.solicitudes.append(("consultar", id_corrida))
        return EstadoCorridaPortal(id_corrida, "procesando", 4, 1)

    def reintentar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
        self.solicitudes.append(("reintentar", id_corrida))
        return EstadoCorridaPortal(id_corrida, "inventariando", 4, 1)


def _solicitar(aplicacion, metodo: str, ruta: str, cuerpo: bytes = b"", tipo: str = "application/json"):
    estado: list[str] = []
    encabezados: list[tuple[str, str]] = []
    respuesta = aplicacion(
        {
            "REQUEST_METHOD": metodo,
            "PATH_INFO": ruta,
            "CONTENT_TYPE": tipo,
            "CONTENT_LENGTH": str(len(cuerpo)),
            "wsgi.input": io.BytesIO(cuerpo),
        },
        lambda codigo, headers: (estado.append(codigo), encabezados.extend(headers)),
    )
    return estado[0], dict(encabezados), json.loads(b"".join(respuesta))


def test_rutas_crean_consultan_y_reintentan_sin_exponer_la_ruta(tmp_path: Path) -> None:
    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio)

    estado_crear, _encabezados, creada = _solicitar(
        aplicacion,
        "POST",
        "/corridas",
        json.dumps({"ruta": str(tmp_path)}).encode(),
    )
    estado_consultar, _encabezados, consultada = _solicitar(aplicacion, "GET", "/corridas/corrida-1")
    estado_reintentar, _encabezados, reintentada = _solicitar(aplicacion, "POST", "/corridas/corrida-1/reintentar")

    assert estado_crear == "202 Accepted"
    assert creada == {"id_corrida": "corrida-1", "estado": "creada", "documentos_pendientes": 0, "cuarentenas": 0}
    assert estado_consultar == "200 OK"
    assert consultada == {"id_corrida": "corrida-1", "estado": "procesando", "documentos_pendientes": 4, "cuarentenas": 1}
    assert estado_reintentar == "202 Accepted"
    assert reintentada["estado"] == "inventariando"
    assert servicio.solicitudes == [("crear", str(tmp_path.resolve())), ("consultar", "corrida-1"), ("reintentar", "corrida-1")]


def test_rutas_rechazan_pdf_secretos_y_rutas_no_autorizadas(tmp_path: Path) -> None:
    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path / "autorizada"], servicio)

    estado_pdf, _encabezados, respuesta_pdf = _solicitar(aplicacion, "POST", "/corridas", b"%PDF-1.7", "application/pdf")
    estado_secreto, _encabezados, respuesta_secreto = _solicitar(
        aplicacion,
        "POST",
        "/corridas",
        json.dumps({"ruta": str(tmp_path / "autorizada"), "secreto": "no-admitido"}).encode(),
    )
    estado_ruta, _encabezados, respuesta_ruta = _solicitar(
        aplicacion,
        "POST",
        "/corridas",
        json.dumps({"ruta": str(tmp_path / "externa")}).encode(),
    )

    assert (estado_pdf, respuesta_pdf) == ("415 Unsupported Media Type", {"codigo": "tipo_de_contenido_no_admitido"})
    assert (estado_secreto, respuesta_secreto) == ("400 Bad Request", {"codigo": "solicitud_no_admitida"})
    assert (estado_ruta, respuesta_ruta) == ("403 Forbidden", {"codigo": "ruta_no_autorizada"})
    assert servicio.solicitudes == []


def _motor_con_corrida(corrida_id: str) -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repositorio = RepositorioCorridas(engine)
    repositorio.crear_corrida(Corrida.crear(corrida_id))
    return engine


def test_el_embudo_de_una_corrida_responde_antes_que_la_rama_generica(tmp_path: Path) -> None:
    """9.1/9.2/9.6/9.7: el orden de despacho, o el 404 asegurado.

    `GET /corridas/{id}/embudo` es un GET que cae hoy en la rama genérica de
    `GET /corridas/...`, donde `_consultar_corrida` rechaza cualquier
    identificador con `/` -- así que sin la comprobación ANTES de esa rama,
    esta prueba recibe 404 en vez de 200 con el embudo real.
    """
    corrida_id = "corrida-embudo-1"
    engine = _motor_con_corrida(corrida_id)
    with Session(engine) as sesion, sesion.begin():
        sesion.add(
            Estudio(
                id_episodio="ep-1",
                tipo_documento="laboratorio",
                fecha_estudio=date(2026, 1, 1),
                precision_hora="ausente",
                clave_documento="clave-embudo-1",
                corrida_id=corrida_id,
            )
        )

    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio, motor_lectura=engine)

    estado, _encabezados, cuerpo = _solicitar(aplicacion, "GET", f"/corridas/{corrida_id}/embudo")

    assert estado == "200 OK"
    assert cuerpo["corrida_id"] == corrida_id
    assert cuerpo["entraron"] == 0  # no se inventarió nada en este test, solo se publicó
    assert cuerpo["publicados"] == 1
    assert cuerpo["apartados"] == 0
    assert cuerpo["cierra"] is False  # 1 publicado contra 0 inventariados: residuo -1
    assert cuerpo["residuo"] == -1
    assert set(cuerpo["estimacion"]) == {"situacion"}  # "midiendo": sin números que adivinar
    assert [e["etapa"] for e in cuerpo["etapas"]] == [
        "ingesta",
        "despacho",
        "extraccion",
        "parseo",
        "reconciliacion",
        "coordinacion",
        "pseudonimizacion",
        "salida",
    ]
    # La ruta genérica NUNCA se llamó con este id -- si hubiera caído ahí,
    # `_ServicioFake.consultar_corrida` habría quedado registrada.
    assert servicio.solicitudes == []


def test_post_reintentar_no_se_rompe_por_el_orden_de_despacho_nuevo(tmp_path: Path) -> None:
    """9.3: no regresión explícita -- `/reintentar` sigue guardado por `metodo == 'POST'`."""
    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio)

    estado, _encabezados, respuesta = _solicitar(aplicacion, "POST", "/corridas/corrida-1/reintentar")

    assert estado == "202 Accepted"
    assert respuesta["estado"] == "inventariando"
    assert servicio.solicitudes == [("reintentar", "corrida-1")]


def test_embudo_sin_base_de_lectura_responde_no_disponibilidad(tmp_path: Path) -> None:
    """9.10/9.11: el plano de control arranca sin motor y la ruta responde 503, no rompe."""
    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio, motor_lectura=None)

    estado, _encabezados, _cuerpo = _solicitar(aplicacion, "GET", "/corridas/corrida-1/embudo")

    assert estado == "503 Service Unavailable"


def _solicitar_html(aplicacion, metodo: str, ruta: str):
    estado: list[str] = []
    encabezados: list[tuple[str, str]] = []
    respuesta = aplicacion(
        {
            "REQUEST_METHOD": metodo,
            "PATH_INFO": ruta,
            "CONTENT_TYPE": "text/plain",
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(b""),
        },
        lambda codigo, headers: (estado.append(codigo), encabezados.extend(headers)),
    )
    return estado[0], dict(encabezados), b"".join(respuesta).decode("utf-8")


def test_get_panel_sirve_el_primer_pintado_ya_con_numeros(tmp_path: Path) -> None:
    """10.8/10.9: la página trae el embudo ya calculado, sin depender de ningún `fetch`."""
    corrida_id = "corrida-panel-1"
    engine = _motor_con_corrida(corrida_id)
    with Session(engine) as sesion, sesion.begin():
        sesion.add(
            Estudio(
                id_episodio="ep-1",
                tipo_documento="laboratorio",
                fecha_estudio=date(2026, 1, 1),
                precision_hora="ausente",
                clave_documento="clave-panel-1",
                corrida_id=corrida_id,
            )
        )

    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio, motor_lectura=engine)

    estado, encabezados, pagina = _solicitar_html(aplicacion, "GET", f"/panel/{corrida_id}")

    assert estado == "200 OK"
    assert encabezados["Content-Type"] == "text/html; charset=utf-8"
    assert corrida_id in pagina
    assert 'id="valor-publicados">1' in pagina
    assert "<script>" in pagina
    # La ruta genérica de `/corridas/...` nunca se llamó con este id.
    assert servicio.solicitudes == []


def test_get_panel_sin_base_de_lectura_responde_no_disponibilidad(tmp_path: Path) -> None:
    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio, motor_lectura=None)

    estado, _encabezados, _pagina = _solicitar_html(aplicacion, "GET", "/panel/corrida-1")

    assert estado == "503 Service Unavailable"


def test_get_panel_de_una_corrida_inexistente_responde_404(tmp_path: Path) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    servicio = _ServicioFake([])
    aplicacion = crear_aplicacion_corridas([tmp_path], servicio, motor_lectura=engine)

    estado, _encabezados, cuerpo = _solicitar(aplicacion, "GET", "/panel/corrida-que-no-existe")

    assert estado == "404 Not Found"
    assert cuerpo == {"codigo": "corrida_no_encontrada"}


def test_crear_corrida_responde_409_cuando_ya_hay_una_activa(tmp_path: Path) -> None:
    """Decisión "dos corridas a la vez": el servicio señala con
    `CorridaEnCursoError` -- la ruta la traduce a `409`, con el id de la
    corrida activa para que el operador sepa cuál está esperando, nunca a un
    `202` que prometería un despacho que el gate acaba de rechazar."""

    @dataclass
    class _ServicioOcupado:
        def crear_corrida(self, ruta_autorizada: str) -> EstadoCorridaPortal:
            raise CorridaEnCursoError("corrida-en-curso-1")

        def consultar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
            raise AssertionError("no se llama en este test")

        def reintentar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
            raise AssertionError("no se llama en este test")

    aplicacion = crear_aplicacion_corridas([tmp_path], _ServicioOcupado())

    estado, _encabezados, cuerpo = _solicitar(
        aplicacion, "POST", "/corridas", json.dumps({"ruta": str(tmp_path)}).encode()
    )

    assert estado == "409 Conflict"
    assert cuerpo == {"codigo": "corrida_en_curso", "id_corrida_activa": "corrida-en-curso-1"}


def test_reintentar_responde_501_cuando_el_servicio_no_lo_implementa(tmp_path: Path) -> None:
    """9.8/9.9: `reintentar_corrida` real lanza `NotImplementedError` -- la ruta responde 501."""

    @dataclass
    class _ServicioSinReintento:
        def crear_corrida(self, ruta_autorizada: str) -> EstadoCorridaPortal:
            raise AssertionError("no se llama en este test")

        def consultar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
            raise AssertionError("no se llama en este test")

        def reintentar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
            raise NotImplementedError("reintentar_corrida: fuera de alcance de panel-de-operacion")

    aplicacion = crear_aplicacion_corridas([tmp_path], _ServicioSinReintento())

    estado, _encabezados, cuerpo = _solicitar(aplicacion, "POST", "/corridas/corrida-1/reintentar")

    assert estado == "501 Not Implemented"
    assert cuerpo == {"codigo": "reintento_no_implementado"}
