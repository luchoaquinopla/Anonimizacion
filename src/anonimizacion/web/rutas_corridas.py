"""Rutas WSGI internas: sólo controlan corridas, nunca transportan PDFs."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class EstadoCorridaPortal:
    """Resumen seguro de una corrida para exponer en la intranet."""

    id_corrida: str
    estado: str
    documentos_pendientes: int
    cuarentenas: int


class ServicioCorridas(Protocol):
    def crear_corrida(self, ruta_autorizada: str) -> EstadoCorridaPortal: ...
    def consultar_corrida(self, id_corrida: str) -> EstadoCorridaPortal: ...
    def reintentar_corrida(self, id_corrida: str) -> EstadoCorridaPortal: ...


InicioRespuesta = Callable[[str, list[tuple[str, str]]], object]
AplicacionWsgi = Callable[[dict[str, object], InicioRespuesta], Iterable[bytes]]


def crear_aplicacion_corridas(raices_autorizadas: Sequence[Path], servicio: ServicioCorridas) -> AplicacionWsgi:
    """Crea el plano de control con una lista cerrada de raíces del servidor."""
    raices = tuple(raiz.resolve() for raiz in raices_autorizadas)

    def aplicacion(entorno: dict[str, object], iniciar_respuesta: InicioRespuesta) -> Iterable[bytes]:
        metodo = str(entorno["REQUEST_METHOD"])
        ruta = str(entorno["PATH_INFO"])
        if metodo == "POST" and ruta == "/corridas":
            return _crear_corrida(entorno, iniciar_respuesta, raices, servicio)
        if metodo == "GET" and ruta.startswith("/corridas/"):
            return _consultar_corrida(iniciar_respuesta, servicio, ruta.removeprefix("/corridas/"))
        if metodo == "POST" and ruta.startswith("/corridas/") and ruta.endswith("/reintentar"):
            id_corrida = ruta.removeprefix("/corridas/").removesuffix("/reintentar").rstrip("/")
            return _responder(iniciar_respuesta, "202 Accepted", servicio.reintentar_corrida(id_corrida))
        return _responder(iniciar_respuesta, "404 Not Found", {"codigo": "ruta_no_encontrada"})

    return aplicacion


def _crear_corrida(
    entorno: dict[str, object],
    iniciar_respuesta: InicioRespuesta,
    raices: tuple[Path, ...],
    servicio: ServicioCorridas,
) -> Iterable[bytes]:
    if str(entorno.get("CONTENT_TYPE", "")).split(";", 1)[0] != "application/json":
        return _responder(iniciar_respuesta, "415 Unsupported Media Type", {"codigo": "tipo_de_contenido_no_admitido"})
    solicitud = _leer_solicitud(entorno)
    if set(solicitud) != {"ruta"} or not isinstance(solicitud["ruta"], str):
        return _responder(iniciar_respuesta, "400 Bad Request", {"codigo": "solicitud_no_admitida"})
    ruta = Path(solicitud["ruta"]).resolve()
    if not any(_esta_dentro_de(ruta, raiz) for raiz in raices):
        return _responder(iniciar_respuesta, "403 Forbidden", {"codigo": "ruta_no_autorizada"})
    return _responder(iniciar_respuesta, "202 Accepted", servicio.crear_corrida(str(ruta)))


def _consultar_corrida(
    iniciar_respuesta: InicioRespuesta, servicio: ServicioCorridas, id_corrida: str
) -> Iterable[bytes]:
    if not id_corrida or "/" in id_corrida:
        return _responder(iniciar_respuesta, "404 Not Found", {"codigo": "ruta_no_encontrada"})
    return _responder(iniciar_respuesta, "200 OK", servicio.consultar_corrida(id_corrida))


def _leer_solicitud(entorno: dict[str, object]) -> dict[str, object]:
    longitud = int(str(entorno.get("CONTENT_LENGTH", "0")) or "0")
    cuerpo = entorno["wsgi.input"].read(longitud)
    try:
        solicitud = json.loads(cuerpo)
    except (TypeError, ValueError):
        return {}
    return solicitud if isinstance(solicitud, dict) else {}


def _esta_dentro_de(ruta: Path, raiz: Path) -> bool:
    try:
        ruta.relative_to(raiz)
    except ValueError:
        return False
    return True


def _responder(iniciar_respuesta: InicioRespuesta, estado: str, contenido: EstadoCorridaPortal | dict[str, str]) -> Iterable[bytes]:
    datos = asdict(contenido) if isinstance(contenido, EstadoCorridaPortal) else contenido
    cuerpo = json.dumps(datos, separators=(",", ":")).encode()
    iniciar_respuesta(estado, [("Content-Type", "application/json"), ("Content-Length", str(len(cuerpo)))])
    return [cuerpo]
