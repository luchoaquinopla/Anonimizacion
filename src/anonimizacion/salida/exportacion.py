"""Exportación derivada (Parquet + manifiesto) del dataset vinculado.

design.md, decisiones 4/5/6: PostgreSQL sigue siendo la única fuente de
verdad (spec `anonymized-output`, requisito MODIFICADO) -- este módulo SOLO
lee, nunca escribe. La vinculación de episodio (paciente + ventana ±7 días)
YA está resuelta al momento de escribir cada `estudio` (`estudio.id_episodio`,
ver `pseudonimizacion/vinculacion.py` y `destinos/postgres.py::escribir_episodio`)
-- exportar no reimplementa esa lógica, sólo agrupa por la clave que ya existe.

Streaming: una transacción, paginación por clave (`id_episodio`, no OFFSET
ciego) de a `TAMANO_PAGINA_DEFECTO` episodios, un `ParquetWriter` por tabla
con un row group por página, escritura en `<archivo>.tmp` + rename atómico.
El manifiesto se escribe último (spec: si el proceso se corta a mitad de
camino, nunca queda un manifiesto declarando datos que no llegaron a
persistirse en disco).

`.tmp` huérfano de una corrida anterior que murió a mitad de camino: no
requiere limpieza manual ni rompe la corrida siguiente. `pq.ParquetWriter`
abre el archivo en modo escritura (equivalente a `wb`, verificado a mano):
una corrida nueva sobre el mismo `<archivo>.parquet.tmp` lo trunca y lo
reescribe desde cero, nunca falla por "archivo ya existe" ni mezcla filas
de la corrida vieja con la nueva.

Lista blanca de columnas (spec "Cero PII en la exportación" + decisión de
comité): afuera `clave_documento`, `corrida_id`, cualquier `id_medico*` y el
texto libre del eco (`texto_seccion_eco`). `adicionales_json` es JSON del
campo `estudio.adicionales`, que YA debería llegar saneado de nombres de
médico/técnico (`constructor_registro.py::_adicionales_sin_personal`,
migración 0014, probado contra Postgres real en
`tests/salida/destinos/test_postgres.py`) -- pero esta capa NO confía
ciegamente en esa garantía de escritura: revisión adversarial (CRÍTICO)
señaló que es una lista fija de 3 claves y la base puede tener filas
escritas por una versión anterior del código (o un parser futuro que la
rompa sin que nadie note la regresión hasta que ya está en el dataset
exportado). Por eso `exportacion.py` vuelve a filtrar `adicionales_json` con
`_CLAVES_PERSONAL` **importada** de `constructor_registro.py` (no una copia
literal -- si esa tupla cambia, el filtro de acá cambia con ella sin
intervención manual), como defensa en profundidad en el ÚLTIMO punto antes
de que el dato salga del sistema (ver `_adicionales_sin_personal_exportacion`,
`test_estudio_adicionales_con_claves_personales_de_una_fila_vieja_nunca_llega_al_parquet`).
"""

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

from ..dominio.senal_ecg import FORMA as FORMA_SENAL
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
# Ventanas de columna del layout del PDF (design.md, `extraccion/senal_ecg.py::OFFSETS_COLUMNA`):
# 4 columnas de 1238 muestras a 500 Hz, salvo V1 (tira de ritmo completa).
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
        ("muestras_uv", pa.list_(pa.int16(), _MUESTRAS_SENAL_APLANADA)),
        ("mascara", pa.list_(pa.bool_(), _MUESTRAS_SENAL_APLANADA)),
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
    """Defensa en profundidad (revisión adversarial, CRÍTICO): filtra de
    nuevo por `_CLAVES_PERSONAL` (importada de `constructor_registro.py`,
    NUNCA una copia literal) en el último punto antes de que el dato salga
    del sistema -- no asume que `estudio.adicionales` ya llegó limpio, aunque
    la escritura ya debería garantizarlo. Cubre filas viejas escritas por una
    versión anterior del código o una regresión futura en el escritor."""
    return {clave: valor for clave, valor in adicionales.items() if clave not in _CLAVES_PERSONAL}


def _json_o_none(valor: dict | None) -> str | None:
    if not valor:
        return None
    return json.dumps(_adicionales_sin_personal_exportacion(valor), sort_keys=True, ensure_ascii=False)


def _ids_episodio_paginados(sesion: Session, *, tamano_pagina: int = TAMANO_PAGINA_DEFECTO) -> Iterator[list[str]]:
    """Paginación por CLAVE (`id_episodio > ultimo`), no por `OFFSET` ciego --
    memoria acotada a `tamano_pagina` filas por consulta, sin importar cuántos
    episodios haya en total (ver test de paginación, que lo verifica contando
    filas materializadas por página, nunca con un umbral de tiempo)."""
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


def _procesar_pagina(sesion: Session, pagina_ids: list[str], escritores: _EscritoresPagina) -> tuple[int, int, int, int]:
    """Arma y escribe las 4 tablas de UNA página de episodios. Extraído de
    `exportar_dataset` para bajar su complejidad ciclomática bajo el límite
    del repo (`pyproject.toml`, `mccabe`, mismo criterio que `construir_senal`
    en la Fase 1 de este cambio)."""
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
    filas_ecg: list[dict] = []
    filas_laboratorio: list[dict] = []
    filas_eco: list[dict] = []

    for estudio in estudios_pagina:
        if estudio.tipo_documento == "ecg":
            tiene_tipo[estudio.id_episodio]["ecg"] = True
            filas_ecg.append(_fila_ecg(estudio, mediciones_ecg.get(estudio.id_estudio), senales.get(estudio.id_estudio)))
        elif estudio.tipo_documento == "laboratorio":
            resultados = resultados_por_estudio.get(estudio.id_estudio, [])
            if resultados:
                tiene_tipo[estudio.id_episodio]["laboratorio"] = True
                filas_laboratorio.extend(_filas_laboratorio(estudio, resultados))
        else:  # ecocardiograma
            tiene_tipo[estudio.id_episodio]["eco"] = True
            filas_eco.append(_fila_eco(estudio, mediciones_eco.get(estudio.id_estudio)))

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
    """Exporta `episodios/ecg/laboratorio/eco.parquet` + `manifiesto.json` a `salida`.

    Sólo lectura de `engine`: ninguna fila de PostgreSQL se modifica (spec
    `exportacion-dataset-vinculado`, "Exportación no muta la base"). Una
    transacción de sólo lectura, `REPEATABLE READ` cuando el dialecto es
    PostgreSQL (snapshot consistente durante toda la exportación, sin
    bloquear escritores) -- SQLite (usado en tests) no soporta ese nivel de
    aislamiento explícito, así que usa el que tenga por defecto.
    """
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
            # Fin del `with sesion.begin()`: transacción de sólo lectura, sin
            # ningún `INSERT`/`UPDATE`/`DELETE` emitido -- se cierra sin
            # commitear ningún cambio (no hay ninguno que commitear).

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
