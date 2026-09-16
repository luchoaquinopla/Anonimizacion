"""Exportación derivada (Parquet + manifiesto) del dataset vinculado: sólo lectura, nunca
escribe. Streaming con paginación por clave, escritura atómica `.tmp`+rename, manifiesto
último (nunca declara datos que no llegaron a disco). Lista blanca de columnas: filtra de
nuevo `adicionales_json` con `_CLAVES_PERSONAL` importada (no copiada) de
`constructor_registro.py`, como defensa en profundidad ante filas viejas o una regresión futura."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import sqlalchemy as sa
from sqlalchemy.orm import Session

from typing import Callable

from ..dominio.senal_ecg import FORMA as FORMA_SENAL
from ..dominio.tipos_documento import TipoDocumento
from .codec_senal import VERSION_FORMATO_ACTUAL, decodificar_mascara, decodificar_muestras
from .constructor_registro import _CLAVES_PERSONAL
from .modelos_orm import Episodio, Estudio, MedicionEco, MedicionEcg, ResultadoLaboratorio, SenalEcgOrm

TAMANO_PAGINA_DEFECTO = 256
VERSION_ESQUEMA_EXPORTACION = 1
VENTANA_VINCULACION_DIAS = 7  # ya aplicada al escribir estudio.id_episodio -- documental acá
NOMBRE_MANIFIESTO = "manifiesto.json"

FRECUENCIA_HZ_SENAL = 500
UNIDAD_MUESTRAS = "uV"
ORDEN_DERIVACIONES = ("I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6")
_FILAS_SENAL, _COLUMNAS_SENAL = FORMA_SENAL  # (12, 5000)
_MUESTRAS_SENAL_APLANADA = _FILAS_SENAL * _COLUMNAS_SENAL  # 60000
# Layout del PDF: 4 columnas de 1238 muestras a 500 Hz, salvo V1 (tira de ritmo completa).
_OFFSETS_COLUMNA = (0, 1250, 2500, 3750)
_MUESTRAS_POR_TRAMO = 1238
_COLUMNAS_DERIVACIONES = (
    ("I", "II", "III"),
    ("aVR", "aVL", "aVF"),
    ("V1", "V2", "V3"),
    ("V4", "V5", "V6"),
)
_DERIVACION_RITMO = "V1"


@dataclass(frozen=True)
class ResumenExportacion:
    episodios: int
    ecg: int
    laboratorio: int
    eco: int


ESQUEMA_EPISODIOS = pa.schema(
    [
        ("id_episodio", pa.string()),
        ("fecha_ancla", pa.date32()),
        ("tiene_ecg", pa.bool_()),
        ("tiene_laboratorio", pa.bool_()),
        ("tiene_eco", pa.bool_()),
        ("completo", pa.bool_()),
    ]
)

ESQUEMA_ECG = pa.schema(
    [
        ("id_episodio", pa.string()),
        ("fecha_estudio", pa.date32()),
        ("hora_estudio", pa.string()),
        ("completo", pa.bool_()),
        ("adicionales_json", pa.string()),
        ("vent_rate", pa.string()),
        ("pr_interval", pa.string()),
        ("qrs_duration", pa.string()),
        ("qt_qtc", pa.string()),
        ("ejes", pa.string()),
        ("tiene_senal", pa.bool_()),
        ("frecuencia_hz", pa.int32()),
        ("version_extractor", pa.int32()),
        ("version_formato", pa.int32()),
        # Lista de largo variable, no FixedSizeListArray: éste no hace round-trip por Parquet cuando toda la página es None (bug de pyarrow 25.0.1).
        ("muestras_uv", pa.list_(pa.int16())),
        ("mascara", pa.list_(pa.bool_())),
    ]
)

ESQUEMA_LABORATORIO = pa.schema(
    [
        ("id_episodio", pa.string()),
        ("fecha_estudio", pa.date32()),
        ("completo", pa.bool_()),
        ("adicionales_json", pa.string()),
        ("analito", pa.string()),
        ("seccion", pa.string()),
        ("valor_num", pa.float64()),
        ("valor_texto", pa.string()),
        ("unidad", pa.string()),
        ("ref_min", pa.float64()),
        ("ref_max", pa.float64()),
    ]
)

ESQUEMA_ECO = pa.schema(
    [
        ("id_episodio", pa.string()),
        ("fecha_estudio", pa.date32()),
        ("completo", pa.bool_()),
        ("adicionales_json", pa.string()),
        ("ao", pa.string()),
        ("ai", pa.string()),
        ("ddvi", pa.string()),
        ("dsvi", pa.string()),
        ("fa", pa.string()),
        ("septum", pa.string()),
        ("p_posterior", pa.string()),
        ("unidades_json", pa.string()),
        ("medidas_extra_json", pa.string()),
    ]
)


def _adicionales_sin_personal_exportacion(adicionales: dict) -> dict:
    """Defensa en profundidad: filtra de nuevo por `_CLAVES_PERSONAL` (importada, no copiada)
    en el último punto antes de que el dato salga -- cubre filas viejas o una regresión futura."""
    return {clave: valor for clave, valor in adicionales.items() if clave not in _CLAVES_PERSONAL}


def _json_o_none(valor: dict | None) -> str | None:
    if not valor:
        return None
    return json.dumps(_adicionales_sin_personal_exportacion(valor), sort_keys=True, ensure_ascii=False)


def _ids_episodio_paginados(sesion: Session, *, tamano_pagina: int = TAMANO_PAGINA_DEFECTO) -> Iterator[list[str]]:
    """Paginación por clave (`id_episodio > ultimo`), no por `OFFSET` ciego: memoria acotada
    a `tamano_pagina` filas, sin importar cuántos episodios haya en total."""
    ultimo: str | None = None
    while True:
        consulta = sa.select(Episodio.id_episodio).order_by(Episodio.id_episodio).limit(tamano_pagina)
        if ultimo is not None:
            consulta = consulta.where(Episodio.id_episodio > ultimo)
        pagina = list(sesion.scalars(consulta).all())
        if not pagina:
            return
        yield pagina
        ultimo = pagina[-1]
        if len(pagina) < tamano_pagina:
            return


def _fila_ecg(estudio: Estudio, medicion: MedicionEcg | None, senal: SenalEcgOrm | None) -> dict:
    tiene_senal = senal is not None
    if tiene_senal:
        muestras = decodificar_muestras(senal.muestras_uv, version_formato=senal.version_formato)
        mascara = decodificar_mascara(senal.mascara, version_formato=senal.version_formato)
        muestras_lista = muestras.reshape(-1).tolist()
        mascara_lista = mascara.reshape(-1).tolist()
        frecuencia_hz = senal.frecuencia_hz
        version_extractor = senal.version_extractor
        version_formato = senal.version_formato
    else:
        muestras_lista = None
        mascara_lista = None
        frecuencia_hz = None
        version_extractor = None
        version_formato = None

    return {
        "id_episodio": estudio.id_episodio,
        "fecha_estudio": estudio.fecha_estudio,
        "hora_estudio": estudio.hora_estudio.isoformat() if estudio.hora_estudio else None,
        "completo": estudio.completo,
        "adicionales_json": _json_o_none(estudio.adicionales),
        "vent_rate": medicion.vent_rate if medicion else None,
        "pr_interval": medicion.pr_interval if medicion else None,
        "qrs_duration": medicion.qrs_duration if medicion else None,
        "qt_qtc": medicion.qt_qtc if medicion else None,
        "ejes": medicion.ejes if medicion else None,
        "tiene_senal": tiene_senal,
        "frecuencia_hz": frecuencia_hz,
        "version_extractor": version_extractor,
        "version_formato": version_formato,
        "muestras_uv": muestras_lista,
        "mascara": mascara_lista,
    }


def _filas_laboratorio(estudio: Estudio, resultados: list[ResultadoLaboratorio]) -> list[dict]:
    adicionales_json = _json_o_none(estudio.adicionales)
    return [
        {
            "id_episodio": estudio.id_episodio,
            "fecha_estudio": estudio.fecha_estudio,
            "completo": estudio.completo,
            "adicionales_json": adicionales_json,
            "analito": fila.analito,
            "seccion": fila.seccion,
            "valor_num": fila.valor_num,
            "valor_texto": fila.valor_texto,
            "unidad": fila.unidad,
            "ref_min": fila.ref_min,
            "ref_max": fila.ref_max,
        }
        for fila in resultados
    ]


def _fila_eco(estudio: Estudio, medicion: MedicionEco | None) -> dict:
    return {
        "id_episodio": estudio.id_episodio,
        "fecha_estudio": estudio.fecha_estudio,
        "completo": estudio.completo,
        "adicionales_json": _json_o_none(estudio.adicionales),
        "ao": medicion.ao if medicion else None,
        "ai": medicion.ai if medicion else None,
        "ddvi": medicion.ddvi if medicion else None,
        "dsvi": medicion.dsvi if medicion else None,
        "fa": medicion.fa if medicion else None,
        "septum": medicion.septum if medicion else None,
        "p_posterior": medicion.p_posterior if medicion else None,
        "unidades_json": _json_o_none(medicion.unidades) if medicion else None,
        "medidas_extra_json": _json_o_none(medicion.adicionales) if medicion else None,
    }


def _ventanas_columna() -> list[dict]:
    ventanas = []
    for indice_columna, derivaciones in enumerate(_COLUMNAS_DERIVACIONES):
        inicio = _OFFSETS_COLUMNA[indice_columna]
        derivaciones_tramo = tuple(d for d in derivaciones if d != _DERIVACION_RITMO)
        if derivaciones_tramo:
            ventanas.append(
                {
                    "columna": indice_columna,
                    "inicio_muestra": inicio,
                    "largo_muestras": _MUESTRAS_POR_TRAMO,
                    "derivaciones": list(derivaciones_tramo),
                }
            )
    ventanas.append(
        {
            "columna": None,
            "inicio_muestra": 0,
            "largo_muestras": _COLUMNAS_SENAL,
            "derivaciones": [_DERIVACION_RITMO],
        }
    )
    return ventanas


def _sha256_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _escribir_atomico(escribir: "callable[[Path], None]", destino: Path) -> None:
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    escribir(temporal)
    temporal.replace(destino)


@dataclass(frozen=True)
class _EscritoresPagina:
    episodios: pq.ParquetWriter
    ecg: pq.ParquetWriter
    laboratorio: pq.ParquetWriter
    eco: pq.ParquetWriter


@dataclass
class _ContextoTipos:
    """Acumuladores por tipo, mutados por cada `_procesar_*`; mismo patrón de whitelist/despacho que `postgres.py`."""

    mediciones_ecg: dict
    senales: dict
    mediciones_eco: dict
    resultados_por_estudio: dict
    filas_ecg: list[dict]
    filas_laboratorio: list[dict]
    filas_eco: list[dict]


def _procesar_ecg(estudio: Estudio, ctx: _ContextoTipos) -> bool:
    ctx.filas_ecg.append(_fila_ecg(estudio, ctx.mediciones_ecg.get(estudio.id_estudio), ctx.senales.get(estudio.id_estudio)))
    return True


def _procesar_laboratorio(estudio: Estudio, ctx: _ContextoTipos) -> bool:
    resultados = ctx.resultados_por_estudio.get(estudio.id_estudio, [])
    if not resultados:
        return False
    ctx.filas_laboratorio.extend(_filas_laboratorio(estudio, resultados))
    return True


def _procesar_eco(estudio: Estudio, ctx: _ContextoTipos) -> bool:
    ctx.filas_eco.append(_fila_eco(estudio, ctx.mediciones_eco.get(estudio.id_estudio)))
    return True


# Se compara contra TipoDocumento.X.value, nunca literales sueltos. Whitelist == despacho: sin entrada levanta ValueError, nunca cae en un else.
_PROCESADORES_POR_TIPO: dict[str, Callable[[Estudio, _ContextoTipos], bool]] = {
    TipoDocumento.ECG.value: _procesar_ecg,
    TipoDocumento.LABORATORIO.value: _procesar_laboratorio,
    TipoDocumento.ECOCARDIOGRAMA.value: _procesar_eco,
}

# No idénticas a TipoDocumento.value ("eco" vs "ecocardiograma"): son nombre de columna Parquet ya publicado.
_CLAVE_TIENE_TIPO_POR_TIPO: dict[str, str] = {
    TipoDocumento.ECG.value: "ecg",
    TipoDocumento.LABORATORIO.value: "laboratorio",
    TipoDocumento.ECOCARDIOGRAMA.value: "eco",
}


def _procesar_pagina(sesion: Session, pagina_ids: list[str], escritores: _EscritoresPagina) -> tuple[int, int, int, int]:
    """Arma y escribe las 4 tablas de UNA página de episodios; extraído para bajar la
    complejidad ciclomática de `exportar_dataset` bajo el límite del repo."""
    episodios_pagina = {
        e.id_episodio: e for e in sesion.scalars(sa.select(Episodio).where(Episodio.id_episodio.in_(pagina_ids)))
    }
    estudios_pagina = list(sesion.scalars(sa.select(Estudio).where(Estudio.id_episodio.in_(pagina_ids))))
    ids_estudio = [e.id_estudio for e in estudios_pagina]

    mediciones_ecg = {
        m.id_estudio: m for m in sesion.scalars(sa.select(MedicionEcg).where(MedicionEcg.id_estudio.in_(ids_estudio)))
    }
    senales = {
        s.id_estudio: s
        for s in sesion.scalars(sa.select(SenalEcgOrm).where(SenalEcgOrm.id_estudio.in_(ids_estudio)))
    }
    mediciones_eco = {
        m.id_estudio: m for m in sesion.scalars(sa.select(MedicionEco).where(MedicionEco.id_estudio.in_(ids_estudio)))
    }
    resultados_por_estudio: dict[int, list[ResultadoLaboratorio]] = {}
    for fila in sesion.scalars(
        sa.select(ResultadoLaboratorio).where(ResultadoLaboratorio.id_estudio.in_(ids_estudio))
    ):
        resultados_por_estudio.setdefault(fila.id_estudio, []).append(fila)

    tiene_tipo: dict[str, dict[str, bool]] = {
        id_ep: {"ecg": False, "laboratorio": False, "eco": False} for id_ep in pagina_ids
    }
    contexto = _ContextoTipos(
        mediciones_ecg=mediciones_ecg,
        senales=senales,
        mediciones_eco=mediciones_eco,
        resultados_por_estudio=resultados_por_estudio,
        filas_ecg=[],
        filas_laboratorio=[],
        filas_eco=[],
    )

    for estudio in estudios_pagina:
        procesador = _PROCESADORES_POR_TIPO.get(estudio.tipo_documento)
        if procesador is None:
            raise ValueError(f"tipo_documento no soportado por _procesar_pagina: {estudio.tipo_documento!r}")
        if procesador(estudio, contexto):
            tiene_tipo[estudio.id_episodio][_CLAVE_TIENE_TIPO_POR_TIPO[estudio.tipo_documento]] = True

    filas_ecg = contexto.filas_ecg
    filas_laboratorio = contexto.filas_laboratorio
    filas_eco = contexto.filas_eco

    filas_episodios = [
        {
            "id_episodio": id_ep,
            "fecha_ancla": episodios_pagina[id_ep].fecha_ancla,
            "tiene_ecg": tiene_tipo[id_ep]["ecg"],
            "tiene_laboratorio": tiene_tipo[id_ep]["laboratorio"],
            "tiene_eco": tiene_tipo[id_ep]["eco"],
            "completo": all(tiene_tipo[id_ep].values()),
        }
        for id_ep in pagina_ids
    ]

    escritores.episodios.write_table(pa.Table.from_pylist(filas_episodios, schema=ESQUEMA_EPISODIOS))
    if filas_ecg:
        escritores.ecg.write_table(pa.Table.from_pylist(filas_ecg, schema=ESQUEMA_ECG))
    if filas_laboratorio:
        escritores.laboratorio.write_table(pa.Table.from_pylist(filas_laboratorio, schema=ESQUEMA_LABORATORIO))
    if filas_eco:
        escritores.eco.write_table(pa.Table.from_pylist(filas_eco, schema=ESQUEMA_ECO))

    return len(filas_episodios), len(filas_ecg), len(filas_laboratorio), len(filas_eco)


def exportar_dataset(
    engine: sa.Engine, salida: Path, *, tamano_pagina: int = TAMANO_PAGINA_DEFECTO
) -> ResumenExportacion:
    """Exporta `episodios/ecg/laboratorio/eco.parquet` + `manifiesto.json` a `salida`. Sólo
    lectura, `REPEATABLE READ` en Postgres (snapshot consistente sin bloquear escritores)."""
    salida.mkdir(parents=True, exist_ok=True)
    opciones = {}
    if engine.dialect.name == "postgresql":
        opciones["isolation_level"] = "REPEATABLE READ"

    contador_episodios = 0
    contador_ecg = 0
    contador_laboratorio = 0
    contador_eco = 0

    rutas_temporales = {
        "episodios": salida / "episodios.parquet.tmp",
        "ecg": salida / "ecg.parquet.tmp",
        "laboratorio": salida / "laboratorio.parquet.tmp",
        "eco": salida / "eco.parquet.tmp",
    }
    rutas_finales = {clave: salida / f"{clave}.parquet" for clave in rutas_temporales}

    with engine.connect().execution_options(**opciones) as conexion, Session(bind=conexion) as sesion:
        with sesion.begin():
            with (
                pq.ParquetWriter(rutas_temporales["episodios"], ESQUEMA_EPISODIOS) as escritor_episodios,
                pq.ParquetWriter(rutas_temporales["ecg"], ESQUEMA_ECG) as escritor_ecg,
                pq.ParquetWriter(rutas_temporales["laboratorio"], ESQUEMA_LABORATORIO) as escritor_laboratorio,
                pq.ParquetWriter(rutas_temporales["eco"], ESQUEMA_ECO) as escritor_eco,
            ):
                escritores = _EscritoresPagina(
                    episodios=escritor_episodios, ecg=escritor_ecg, laboratorio=escritor_laboratorio, eco=escritor_eco
                )
                for pagina_ids in _ids_episodio_paginados(sesion, tamano_pagina=tamano_pagina):
                    n_episodios, n_ecg, n_laboratorio, n_eco = _procesar_pagina(sesion, pagina_ids, escritores)
                    contador_episodios += n_episodios
                    contador_ecg += n_ecg
                    contador_laboratorio += n_laboratorio
                    contador_eco += n_eco
            # Transacción de sólo lectura: se cierra sin commitear ningún cambio.

    for clave, temporal in rutas_temporales.items():
        temporal.replace(rutas_finales[clave])

    manifiesto = {
        "version_esquema_exportacion": VERSION_ESQUEMA_EXPORTACION,
        "frecuencia_hz": FRECUENCIA_HZ_SENAL,
        "unidad_muestras": UNIDAD_MUESTRAS,
        "orden_derivaciones": list(ORDEN_DERIVACIONES),
        "version_formato": VERSION_FORMATO_ACTUAL,
        "ventanas_columna": _ventanas_columna(),
        "ventana_vinculacion_dias": VENTANA_VINCULACION_DIAS,
        "conteos": {
            "episodios": contador_episodios,
            "ecg": contador_ecg,
            "laboratorio": contador_laboratorio,
            "eco": contador_eco,
        },
        "archivos": {
            clave: {"sha256": _sha256_archivo(ruta)} for clave, ruta in rutas_finales.items()
        },
    }

    def _escribir_manifiesto(destino: Path) -> None:
        destino.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8")

    _escribir_atomico(_escribir_manifiesto, salida / NOMBRE_MANIFIESTO)

    return ResumenExportacion(
        episodios=contador_episodios, ecg=contador_ecg, laboratorio=contador_laboratorio, eco=contador_eco
    )
