"""Rutas WSGI internas: sólo controlan corridas, nunca transportan PDFs."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine


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


def crear_aplicacion_corridas(
    raices_autorizadas: Sequence[Path],
    servicio: ServicioCorridas,
    motor_lectura: Engine | None = None,
) -> AplicacionWsgi:
    """Crea el plano de control con una lista cerrada de raíces del servidor.

    `motor_lectura` es opcional: sin él, el reporte de cuarentena y el embudo
    responden 503 en vez de romper (spec `portal-de-corridas` delta, "el plano
    de control se levanta sin base de lectura conectada"). El plano de
    control tiene que poder levantarse aunque la base de lectura todavía no
    esté conectada.
    """
    raices = tuple(raiz.resolve() for raiz in raices_autorizadas)

    def aplicacion(entorno: dict[str, object], iniciar_respuesta: InicioRespuesta) -> Iterable[bytes]:
        metodo = str(entorno["REQUEST_METHOD"])
        ruta = str(entorno["PATH_INFO"])
        if metodo == "POST" and ruta == "/corridas":
            return _crear_corrida(entorno, iniciar_respuesta, raices, servicio)
        if metodo == "GET" and ruta == "/cuarentena":
            return _reporte_cuarentena(iniciar_respuesta, motor_lectura)
        # Tiene que evaluarse ANTES de la rama genérica de abajo: un GET acá
        # es un `/corridas/...` cualquiera, y `_consultar_corrida` rechaza
        # cualquier identificador con `/` -- sin esta comprobación primero,
        # `/corridas/{id}/embudo` cae en esa rama y da 404 (design.md, "Orden
        # de despacho, o el 404 asegurado"). NO afecta a `/reintentar`
        # (abajo): esa rama exige POST, y ésta exige GET.
        if metodo == "GET" and ruta.startswith("/corridas/") and ruta.endswith("/embudo"):
            id_corrida = ruta.removeprefix("/corridas/").removesuffix("/embudo").rstrip("/")
            return _embudo_corrida(iniciar_respuesta, motor_lectura, id_corrida)
        if metodo == "GET" and ruta.startswith("/panel/"):
            id_corrida = ruta.removeprefix("/panel/").rstrip("/")
            return _panel_corrida(iniciar_respuesta, motor_lectura, id_corrida)
        if metodo == "GET" and ruta.startswith("/corridas/"):
            return _consultar_corrida(iniciar_respuesta, servicio, ruta.removeprefix("/corridas/"))
        if metodo == "POST" and ruta.startswith("/corridas/") and ruta.endswith("/reintentar"):
            id_corrida = ruta.removeprefix("/corridas/").removesuffix("/reintentar").rstrip("/")
            return _reintentar_corrida(entorno, iniciar_respuesta, servicio, id_corrida)
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
    # `CorridaEnCursoError` vive en `ingesta/lanzador_corrida.py` (revisión
    # adversarial ronda 3: es el gate a nivel de BASE, no sólo del panel --
    # `LanzadorCorrida.lanzar()` es quien la lanza de verdad). Import a nivel
    # de módulo acá sería seguro (no hay ciclo con `ingesta`), pero se
    # mantiene diferido por coherencia con el resto de los imports
    # perezosos de este módulo (`_embudo_corrida`/`_panel_corrida` más abajo).
    from anonimizacion.ingesta.lanzador_corrida import CorridaEnCursoError

    try:
        return _responder(iniciar_respuesta, "202 Accepted", servicio.crear_corrida(str(ruta)))
    except CorridaEnCursoError as error:
        # Decisión "dos corridas a la vez" (feature `despachador-desde-el-panel`):
        # `409`, no un `202` que prometería un despacho que el gate acaba de
        # rechazar -- el operador ve CUÁL corrida sigue activa, no sólo que
        # algo salió mal.
        return _responder(
            iniciar_respuesta,
            "409 Conflict",
            {"codigo": "corrida_en_curso", "id_corrida_activa": error.id_corrida_activa},
        )


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


def _responder(
    iniciar_respuesta: InicioRespuesta, estado: str, contenido: EstadoCorridaPortal | dict[str, object]
) -> Iterable[bytes]:
    datos = asdict(contenido) if isinstance(contenido, EstadoCorridaPortal) else contenido
    cuerpo = json.dumps(datos, separators=(",", ":")).encode()
    iniciar_respuesta(estado, [("Content-Type", "application/json"), ("Content-Length", str(len(cuerpo)))])
    return [cuerpo]


def _reintentar_corrida(
    entorno: dict[str, object], iniciar_respuesta: InicioRespuesta, servicio: ServicioCorridas, id_corrida: str
) -> Iterable[bytes]:
    """202 con el desglose reintentados/descartados (feature `reanudacion-de-corridas`).

    Mismo chequeo de `Content-Type: application/json` que `_crear_corrida`
    (revisión de seguridad, feature `acceso-al-panel`): sin esto, un
    `<form>` sin una línea de JavaScript (Basic Auth cacheado por el
    navegador, ver `autenticacion_panel.py`) podría disparar un reintento
    real sin que ningún preflight CORS lo frene.

    `CorridaEnCursoError`/`CorridaNoEncontradaError` viven en
    `ingesta/lanzador_corrida.py` -- import diferido, misma razón que en
    `_crear_corrida`. `NotImplementedError` se conserva por compatibilidad
    con implementaciones de `ServicioCorridas` que todavía no reintenten de
    verdad (ver `tests/web/test_rutas_corridas.py`, el doble que la sigue
    lanzando a propósito).
    """
    if str(entorno.get("CONTENT_TYPE", "")).split(";", 1)[0] != "application/json":
        return _responder(iniciar_respuesta, "415 Unsupported Media Type", {"codigo": "tipo_de_contenido_no_admitido"})

    from anonimizacion.ingesta.lanzador_corrida import CorridaEnCursoError, CorridaNoEncontradaError

    try:
        return _responder(iniciar_respuesta, "202 Accepted", servicio.reintentar_corrida(id_corrida))
    except NotImplementedError:
        return _responder(iniciar_respuesta, "501 Not Implemented", {"codigo": "reintento_no_implementado"})
    except CorridaEnCursoError as error:
        return _responder(
            iniciar_respuesta,
            "409 Conflict",
            {"codigo": "corrida_en_curso", "id_corrida_activa": error.id_corrida_activa},
        )
    except CorridaNoEncontradaError:
        return _responder(iniciar_respuesta, "404 Not Found", {"codigo": "corrida_no_encontrada"})


def _embudo_corrida(
    iniciar_respuesta: InicioRespuesta, motor_lectura: Engine | None, id_corrida: str
) -> Iterable[bytes]:
    """Sirve el contrato JSON completo del embudo (design.md, "El contrato JSON")."""
    if not id_corrida or "/" in id_corrida:
        return _responder(iniciar_respuesta, "404 Not Found", {"codigo": "ruta_no_encontrada"})
    if motor_lectura is None:
        return _responder(iniciar_respuesta, "503 Service Unavailable", {"codigo": "base_de_lectura_no_configurada"})

    from .servicio_corridas import construir_payload_embudo

    payload = construir_payload_embudo(motor_lectura, id_corrida)
    if payload is None:
        return _responder(iniciar_respuesta, "404 Not Found", {"codigo": "corrida_no_encontrada"})
    return _responder(iniciar_respuesta, "200 OK", payload)


def _panel_corrida(
    iniciar_respuesta: InicioRespuesta, motor_lectura: Engine | None, id_corrida: str
) -> Iterable[bytes]:
    """Sirve la página del panel con el embudo ya calculado (design.md, "Las rutas").

    Hereda la guarda de 9.11 (503 sin base de lectura) y reusa el mismo
    payload que sirve `GET /corridas/{id}/embudo`: el primer pintado y cada
    refresco posterior parten de la misma forma exacta.
    """
    if not id_corrida or "/" in id_corrida:
        return _responder(iniciar_respuesta, "404 Not Found", {"codigo": "ruta_no_encontrada"})
    if motor_lectura is None:
        iniciar_respuesta("503 Service Unavailable", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"base de lectura no configurada"]

    from .plantilla_panel import renderizar_panel
    from .servicio_corridas import construir_payload_embudo

    payload = construir_payload_embudo(motor_lectura, id_corrida)
    if payload is None:
        return _responder(iniciar_respuesta, "404 Not Found", {"codigo": "corrida_no_encontrada"})

    cuerpo = renderizar_panel(payload).encode("utf-8")
    iniciar_respuesta(
        "200 OK",
        [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(cuerpo)))],
    )
    return [cuerpo]


def _reporte_cuarentena(iniciar_respuesta: InicioRespuesta, motor_lectura: object | None) -> Iterable[bytes]:
    """Sirve el reporte de estudios apartados, agrupado por qué hacer con cada uno."""
    if motor_lectura is None:
        iniciar_respuesta("503 Service Unavailable", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"base de lectura no configurada"]

    from .plantilla_reporte import renderizar_reporte
    from .reporte_cuarentena import construir_reporte

    cuerpo = renderizar_reporte(construir_reporte(motor_lectura)).encode("utf-8")
    iniciar_respuesta(
        "200 OK",
        [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(cuerpo)))],
    )
    return [cuerpo]
