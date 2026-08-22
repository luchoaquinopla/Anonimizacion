from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

from anonimizacion.web.rutas_corridas import EstadoCorridaPortal, crear_aplicacion_corridas


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
