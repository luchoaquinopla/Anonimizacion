"""Modelo de lectura del embudo de una corrida: cuenta lo que el pipeline ya escribió.

El panel no mide -- lee `documento_corrida` (el denominador), `estudio` (los
publicados) y `cuarentena` (los apartados) con tres consultas agregadas
(design.md, "Consultas del panel"). Ningún `count(*)` trae una fila entera al
proceso, y ninguna de las tres proyecta `ruta_autorizada` ni `huella_contenido`
(Requisito 6 de la spec: el panel no expone PII).

Este módulo NO renderiza: la presentación vive en `plantilla_panel.py`
(Tramo 5), igual que `reporte_cuarentena.py`/`plantilla_reporte.py` ya separan
datos de HTML.

La línea que no se cruza (design.md, Decisión 5): este módulo **nunca** lee
`documento_corrida.estado`. El vocabulario de estados modelado (`CREADA`,
`INVENTARIANDO`, ...) no describe el recorrido real del pipeline; leerlo
mostraría 100% "inventariado" para siempre. `calcular_embudo` recibe conteos
ya agregados y no ve ninguna fila cruda, así que no hay ninguna columna
`estado` que consultar por accidente.

El residuo va SIEMPRE con signo (design.md, Decisión 9): `residuo = entraron
- (publicados + apartados)`, `cierra = residuo >= 0`. Ningún `max(0, ...)` en
ningún punto del cálculo -- un residuo negativo es la única señal disponible
de que un documento quedó contado en más de un destino.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.salida.modelos_orm import Cuarentena, DocumentoCorridaOrm, Estudio

#: Orden de EJECUCIÓN real (design.md, Decisión 8) -- NO el orden del enum
#: `Etapa` (`pipeline/etapas.py`), que declara `COORDINACION` entre
#: `RECONCILIACION` y `DETECCION_PII`. El recorrido real de un documento
#: termina en pseudonimización y recién después corre `_coordinar_resueltos`.
#: `deteccion` y `deteccion_pii` quedan fuera: ninguna de las dos produce
#: cuarentena (Requisito 2 de la spec).
ETAPAS_EMBUDO: tuple[str, ...] = (
    "ingesta",
    "extraccion",
    "parseo",
    "reconciliacion",
    "coordinacion",
    "pseudonimizacion",
    "salida",
)

_CODIGO_SOBRETAMANO = "artefacto_sobretamano"
_VENTANA_RECIENTE_SEG = 5 * 60
_MINIMO_TERMINADOS_PARA_ESTIMAR = 200
_TTL_MEMOIZACION_SEG = 1.0

_SituacionEstimacion = Literal["disponible", "midiendo", "sin_avance", "descuadre"]
_Marcha = Literal["en_vuelo", "sin_avance", "completa", "descuadre"]


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PerdidaEtapa:
    """Cuántos documentos llegaron a esta etapa y cuántos se apartaron acá.

    `codigos` es la apertura por motivo (design.md, consulta 3): abierta a
    propósito, sin PII -- son los mismos códigos de `CodigoErrorDocumento`.
    """

    etapa: str
    llegaron: int
    apartados: int
    codigos: Mapping[str, int]


@dataclass(frozen=True)
class Estimacion:
    """Rango de tiempo restante, nunca un número puntual (Requisito 4)."""

    situacion: _SituacionEstimacion
    restante_seg_min: int | None = None
    restante_seg_max: int | None = None


@dataclass(frozen=True)
class Embudo:
    """El contrato completo que sirve `GET /corridas/{id}/embudo`."""

    corrida_id: str
    generado_en: datetime
    entraron: int
    publicados: int
    apartados: int
    residuo: int
    cierra: bool
    marcha: _Marcha
    etapas: tuple[PerdidaEtapa, ...]
    throughput_por_hora: Mapping[str, float]
    estimacion: Estimacion


def _marcha(*, residuo: int, terminados_en_ventana: int) -> _Marcha:
    if residuo < 0:
        return "descuadre"
    if residuo == 0:
        return "completa"
    if terminados_en_ventana > 0:
        return "en_vuelo"
    return "sin_avance"


def _estimar(
    *,
    entraron: int,
    terminados: int,
    terminados_en_ventana: int,
    primero: datetime | None,
    ultimo: datetime | None,
) -> tuple[Estimacion, dict[str, float]]:
    """Las dos cotas del rango de tiempo restante y sus seis bordes (design.md).

    Orden de las comprobaciones, de la más a la menos severa -- design.md no
    fija una prioridad explícita entre "restante < 0" y "ventana vacía", así
    que se resuelve a favor de reportar primero lo más grave: un descuadre
    importa más que la ausencia de avance reciente.
    """
    throughput = {"optimista": 0.0, "pesimista": 0.0}

    if entraron == 0:
        return Estimacion(situacion="midiendo"), throughput
    if terminados < _MINIMO_TERMINADOS_PARA_ESTIMAR:
        return Estimacion(situacion="midiendo"), throughput

    restante = entraron - terminados

    tasa_pesimista_seg = 0.0
    if primero is not None and ultimo is not None and ultimo > primero:
        tasa_pesimista_seg = terminados / (ultimo - primero).total_seconds()
    tasa_optimista_seg = terminados_en_ventana / _VENTANA_RECIENTE_SEG
    throughput = {
        "optimista": round(tasa_optimista_seg * 3600, 2),
        "pesimista": round(tasa_pesimista_seg * 3600, 2),
    }

    if restante < 0:
        return Estimacion(situacion="descuadre"), throughput
    if restante == 0:
        return Estimacion(situacion="disponible", restante_seg_min=0, restante_seg_max=0), throughput
    if terminados_en_ventana == 0:
        return Estimacion(situacion="sin_avance"), throughput
    if tasa_optimista_seg <= 0 or tasa_pesimista_seg <= 0:
        # No debería alcanzarse con los guardas de arriba (terminados >= 200 y
        # ventana no vacía ya implican tasas positivas), pero evita un
        # ZeroDivisionError si algún llamador futuro los rodea.
        return Estimacion(situacion="sin_avance"), throughput

    return (
        Estimacion(
            situacion="disponible",
            restante_seg_min=round(restante / tasa_optimista_seg),
            restante_seg_max=round(restante / tasa_pesimista_seg),
        ),
        throughput,
    )


def calcular_embudo(
    *,
    corrida_id: str,
    entraron: int,
    publicados: int,
    perdidas: Mapping[str, Mapping[str, int]],
    terminados_en_ventana: int,
    primero: datetime | None,
    ultimo: datetime | None,
    ahora: datetime,
) -> Embudo:
    """La aritmética pura del embudo -- sin motor, sin I/O (design.md, Decisión 8 y 9).

    `perdidas` es `{etapa: {codigo: cantidad}}`, ya agregado -- la forma que
    entrega la consulta (3) del diseño agrupada por `etapa, codigo`.
    `terminados_en_ventana`/`primero`/`ultimo` ya excluyen
    `artefacto_sobretamano` (Requisito 4): ese documento nunca se leyó, así
    que no participa del throughput ni de la serie de tiempo.
    """
    apartados = sum(sum(codigos.values()) for codigos in perdidas.values())
    apartados_sobretamano = perdidas.get("ingesta", {}).get(_CODIGO_SOBRETAMANO, 0)
    con_desenlace = publicados + apartados
    residuo = entraron - con_desenlace
    cierra = residuo >= 0

    etapas: list[PerdidaEtapa] = []
    llegaron = con_desenlace
    for etapa in ETAPAS_EMBUDO:
        codigos = dict(perdidas.get(etapa, {}))
        apartados_etapa = sum(codigos.values())
        etapas.append(PerdidaEtapa(etapa=etapa, llegaron=llegaron, apartados=apartados_etapa, codigos=codigos))
        llegaron -= apartados_etapa

    terminados = publicados + apartados - apartados_sobretamano
    estimacion, throughput = _estimar(
        entraron=entraron,
        terminados=terminados,
        terminados_en_ventana=terminados_en_ventana,
        primero=primero,
        ultimo=ultimo,
    )

    return Embudo(
        corrida_id=corrida_id,
        generado_en=ahora,
        entraron=entraron,
        publicados=publicados,
        apartados=apartados,
        residuo=residuo,
        cierra=cierra,
        marcha=_marcha(residuo=residuo, terminados_en_ventana=terminados_en_ventana),
        etapas=tuple(etapas),
        throughput_por_hora=throughput,
        estimacion=estimacion,
    )


#: Memoización de un segundo por `corrida_id` (design.md, "Plan de acceso a
#: 100.000 documentos y 1-2 s"): cinco espectadores refrescando pasan a costar
#: lo mismo que uno. Clave = `corrida_id`, valor = `(marca de reloj monotónico,
#: Embudo)`. Los tests que necesitan bypassear la memoización llaman
#: `_CACHE.clear()` -- acceso directo deliberado, no una API pública nueva sin
#: llamador real.
#:
#: `design.md` fija el TTL pero no dice nada de purgar -- completándolo, no
#: contradiciéndolo: un plano de control que corre meses sin reiniciarse
#: acumularía una entrada MUERTA por cada `corrida_id` que alguna vez se
#: consultó, para siempre, si nada la sacara. Se eligió purgar las entradas
#: vencidas en cada lectura (`_purgar_vencidas`, llamada al principio de
#: `construir_embudo`) en vez de un tope de tamaño con desalojo LRU: el TTL ya
#: es de un segundo, así que el costo de purgar es barrer un dict con a lo
#: sumo "corridas distintas consultadas en el último segundo" entradas --
#: nunca más que eso, porque cualquier entrada más vieja ya se purgó en la
#: lectura anterior. Un tope de tamaño exigiría además una política de
#: desalojo (LRU u otra) para decidir CUÁL corrida sacar bajo presión, y acá
#: no hace falta: el TTL ya acota el tamaño solo.
_CACHE: dict[str, tuple[float, Embudo]] = {}


def _purgar_vencidas(marca: float) -> None:
    vencidas = [
        corrida_id
        for corrida_id, (marca_cacheada, _) in _CACHE.items()
        if (marca - marca_cacheada) >= _TTL_MEMOIZACION_SEG
    ]
    for corrida_id in vencidas:
        del _CACHE[corrida_id]


def _min_opcional(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _max_opcional(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def construir_embudo(
    motor: Engine,
    corrida_id: str,
    *,
    ahora: datetime | None = None,
    reloj: Callable[[], float] = time.monotonic,
) -> Embudo:
    """Lee las tres consultas agregadas del diseño y arma el embudo real.

    Nunca proyecta `ruta_autorizada` ni `huella_contenido` (Requisito 6):
    `documento_corrida` sólo aporta un `count(*)`, y `estudio`/`cuarentena`
    sólo aportan columnas de conteo y de tiempo, nunca la fila completa.
    Nunca lee `documento_corrida.estado` (Decisión 5): el `count(*)` no
    proyecta esa columna.

    `reloj` es inyectable (mismo patrón que `dormir` en
    `pipeline/ejecutor.py`): en producción es `time.monotonic`, y los tests
    que necesitan simular el paso del tiempo -- por ejemplo, para confirmar
    que `_CACHE` purga entradas vencidas -- pasan uno propio.
    """
    momento = ahora if ahora is not None else _ahora_utc()
    marca = reloj()
    _purgar_vencidas(marca)
    cacheado = _CACHE.get(corrida_id)
    if cacheado is not None and (marca - cacheado[0]) < _TTL_MEMOIZACION_SEG:
        return cacheado[1]

    desde = momento - timedelta(seconds=_VENTANA_RECIENTE_SEG)

    with Session(motor) as sesion:
        entraron = (
            sesion.scalar(
                sa.select(sa.func.count())
                .select_from(DocumentoCorridaOrm)
                .where(DocumentoCorridaOrm.corrida_id == corrida_id)
            )
            or 0
        )

        publicados, primero_pub, ultimo_pub, en_ventana_pub = sesion.execute(
            sa.select(
                sa.func.count(),
                sa.func.min(Estudio.creado_en),
                sa.func.max(Estudio.creado_en),
                sa.func.sum(sa.case((Estudio.creado_en >= desde, 1), else_=0)),
            ).where(Estudio.corrida_id == corrida_id)
        ).one()
        publicados = publicados or 0
        en_ventana_pub = en_ventana_pub or 0

        filas_cuarentena = sesion.execute(
            sa.select(
                Cuarentena.etapa,
                Cuarentena.codigo,
                sa.func.count(),
                sa.func.min(Cuarentena.creado_en),
                sa.func.max(Cuarentena.creado_en),
                sa.func.sum(sa.case((Cuarentena.creado_en >= desde, 1), else_=0)),
            )
            .where(Cuarentena.corrida_id == corrida_id)
            .group_by(Cuarentena.etapa, Cuarentena.codigo)
        ).all()

    perdidas: dict[str, dict[str, int]] = {}
    primero_apt: datetime | None = None
    ultimo_apt: datetime | None = None
    en_ventana_apt = 0
    for etapa, codigo, caidos, primero_grp, ultimo_grp, en_ventana_grp in filas_cuarentena:
        perdidas.setdefault(etapa, {})[codigo] = caidos
        if codigo == _CODIGO_SOBRETAMANO:
            # Cuenta en la barra de la etapa (arriba) pero no en la serie de
            # tiempo ni en la ventana: nunca se leyó (Requisito 4).
            continue
        primero_apt = _min_opcional(primero_apt, primero_grp)
        ultimo_apt = _max_opcional(ultimo_apt, ultimo_grp)
        en_ventana_apt += en_ventana_grp or 0

    embudo = calcular_embudo(
        corrida_id=corrida_id,
        entraron=entraron,
        publicados=publicados,
        perdidas=perdidas,
        terminados_en_ventana=en_ventana_pub + en_ventana_apt,
        primero=_min_opcional(primero_pub, primero_apt),
        ultimo=_max_opcional(ultimo_pub, ultimo_apt),
        ahora=momento,
    )
    _CACHE[corrida_id] = (marca, embudo)
    return embudo
