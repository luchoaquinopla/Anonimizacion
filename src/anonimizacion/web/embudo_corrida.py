"""Modelo de lectura del embudo de una corrida: cuenta lo que el pipeline ya escribió,
sin exponer PII (Requisito 6) ni leer `documento_corrida.estado` (no renderiza, eso vive
en `plantilla_panel.py`). El residuo va siempre con signo -- nunca `max(0, ...)` -- porque
un residuo negativo es la única señal de que un documento quedó contado dos veces."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Literal

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.pipeline.etapas import Etapa
from anonimizacion.salida.modelos_orm import Cuarentena, DocumentoCorridaOrm, Estudio

#: Orden de EJECUCIÓN real (design.md D4), no el de declaración de `Etapa` -- deliberadamente
#: explícito para que agregar un miembro al enum no reordene esta vista sin decisión editada
#: acá. `DESPACHO` va justo después de `INGESTA`: es el único punto donde un documento ya
#: inventariado pudo detenerse sin llegar a ninguna etapa posterior.
ORDEN_EMBUDO: tuple[Etapa, ...] = (
    Etapa.INGESTA,
    Etapa.DESPACHO,
    Etapa.EXTRACCION,
    Etapa.PARSEO,
    Etapa.RECONCILIACION,
    Etapa.COORDINACION,
    Etapa.PSEUDONIMIZACION,
    Etapa.SALIDA,
)

#: Excluidas a propósito de `ORDEN_EMBUDO`: ninguna produce cuarentena.
ETAPAS_EXCLUIDAS_DEL_EMBUDO: tuple[Etapa, ...] = (
    Etapa.DETECCION,
    Etapa.DETECCION_PII,
)

ETAPAS_EMBUDO: tuple[str, ...] = tuple(etapa.value for etapa in ORDEN_EMBUDO)

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
    `codigos` abre por motivo, sin PII (mismos códigos de `CodigoErrorDocumento`)."""

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
    # De los publicados, cuántos quedaron incompletos y por qué id_campo (vocabulario
    # cerrado). Default 0/{}: no rompe llamadores existentes que no pasan estos agregados.
    publicados_incompletos: int = 0
    campos_no_extraidos: Mapping[str, int] = field(default_factory=dict)


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
    """Las dos cotas del rango de tiempo restante (design.md). Orden de mayor a menor
    severidad: un descuadre importa más que la ausencia de avance reciente."""
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
        # Guarda contra ZeroDivisionError si algún llamador futuro rodea los checks de arriba.
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
    publicados_incompletos: int = 0,
    campos_no_extraidos: Mapping[str, int] = MappingProxyType({}),
) -> Embudo:
    """La aritmética pura del embudo -- sin motor, sin I/O (design.md). `perdidas` es
    `{etapa: {codigo: cantidad}}` ya agregado; un publicado incompleto sigue siendo
    publicado y no resta de `llegaron` ni aparece en `perdidas`."""
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
        publicados_incompletos=publicados_incompletos,
        campos_no_extraidos=dict(campos_no_extraidos),
    )


#: Memoización de 1s por `corrida_id` (design.md): purga en cada lectura en vez de
#: LRU con tope de tamaño -- el TTL corto ya acota cuánto puede crecer el dict.
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
    """Lee las tres consultas agregadas del diseño y arma el embudo real, sin proyectar
    PII ni `estado`. `reloj` es inyectable para que los tests simulen el paso del tiempo."""
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

        # campos_no_extraidos es JSON (lista de id_campo): no se agrega en SQL portable
        # (SQLite vs Postgres), se agrega en Python más abajo.
        filas_incompletas = sesion.execute(
            sa.select(Estudio.campos_no_extraidos)
            .where(Estudio.corrida_id == corrida_id, Estudio.completo.is_(False))
        ).scalars().all()

    perdidas: dict[str, dict[str, int]] = {}
    primero_apt: datetime | None = None
    ultimo_apt: datetime | None = None
    en_ventana_apt = 0
    for etapa, codigo, caidos, primero_grp, ultimo_grp, en_ventana_grp in filas_cuarentena:
        perdidas.setdefault(etapa, {})[codigo] = caidos
        if codigo == _CODIGO_SOBRETAMANO:
            # Cuenta en la barra de la etapa pero no en throughput/ventana: nunca se leyó.
            continue
        primero_apt = _min_opcional(primero_apt, primero_grp)
        ultimo_apt = _max_opcional(ultimo_apt, ultimo_grp)
        en_ventana_apt += en_ventana_grp or 0

    campos_no_extraidos: dict[str, int] = {}
    for campos in filas_incompletas:
        for id_campo in campos or ():
            campos_no_extraidos[id_campo] = campos_no_extraidos.get(id_campo, 0) + 1

    embudo = calcular_embudo(
        corrida_id=corrida_id,
        entraron=entraron,
        publicados=publicados,
        perdidas=perdidas,
        terminados_en_ventana=en_ventana_pub + en_ventana_apt,
        primero=_min_opcional(primero_pub, primero_apt),
        ultimo=_max_opcional(ultimo_pub, ultimo_apt),
        publicados_incompletos=len(filas_incompletas),
        campos_no_extraidos=campos_no_extraidos,
        ahora=momento,
    )
    _CACHE[corrida_id] = (marca, embudo)
    return embudo
