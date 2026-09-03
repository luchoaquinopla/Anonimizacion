"""Escritor del destino Parquet (tasks.md 7.4, design.md decisión Q1: capa de consumo del pipeline de DL).

`EscritorParquet` es DERIVADA de Postgres, no la fuente de verdad (design.md,
decisión Q1) -- toma los mismos `RegistroAnonimizado` que
`destinos/postgres.py` y los exporta a un dataset Parquet columnar,
particionado por `tipo_documento/año` (un subárbol de directorio por
`tipo_documento`, porque cada uno tiene columnas distintas, más partición
`anio=<año>` dentro con `pyarrow.parquet.write_to_dataset`).

`eco` genera DOS datasets (`eco_medidas`, `eco_texto`) porque
`ContenidoEcoSalida` mezcla dos formas distintas (medidas numeradas +
texto libre por sección) que no caben en una sola tabla columnar sin
duplicar filas de texto por cada medida. A diferencia de
`destinos/postgres.py` (que pivotea las medidas de eco a columnas anchas
fijas, ver `_PIVOTE_MEDIDAS_ECO`), acá se mantienen como filas
`nombre/valor/unidad` -- Parquet es la capa de lectura para entrenamiento,
no impone la misma forma "ancha" que el esquema transaccional; un pivote a
ancho, si hace falta, es un paso de feature-building aguas abajo del
dataset (ver design.md, rationale de la decisión Q1: "pivot a ancho en
feature-building").
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from anonimizacion.dominio.modelos import RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.salida.modelos_salida import ContenidoEcgSalida, ContenidoEcoSalida, ContenidoLaboratorioSalida


# Gotcha 4 (design.md, decisión 3): `pa.Table.from_pylist` infiere el tipo de
# columna por LOTE. Un lote compuesto enteramente por ecocardiogramas (todos
# con `hora_estudio=None`) dejaría esa columna con tipo `null` inferido, que
# choca al leer un dataset combinado junto a la partición de ECG (que sí trae
# strings). Se declara un `pa.schema` explícito por dataset -- `hora_estudio`
# es ISO string o `None`, `precision_hora` siempre string (nunca ausente:
# `PrecisionHora.AUSENTE.value` para los casos sin hora).
_SCHEMA_LABORATORIO = pa.schema([
    ("id_paciente", pa.string()),
    ("id_episodio", pa.string()),
    ("id_medico", pa.string()),
    ("anio", pa.int64()),
    ("fecha_estudio", pa.string()),
    ("analito", pa.string()),
    ("seccion", pa.string()),
    ("valor_num", pa.float64()),
    ("valor_texto", pa.string()),
    ("unidad", pa.string()),
    ("ref_min", pa.float64()),
    ("ref_max", pa.float64()),
    ("hora_estudio", pa.string()),
    ("precision_hora", pa.string()),
])

_SCHEMA_ECG = pa.schema([
    ("id_paciente", pa.string()),
    ("id_episodio", pa.string()),
    ("id_medico", pa.string()),
    ("anio", pa.int64()),
    ("fecha_estudio", pa.string()),
    ("vent_rate", pa.string()),
    ("pr_interval", pa.string()),
    ("qrs_duration", pa.string()),
    ("qt_qtc", pa.string()),
    ("ejes", pa.string()),
    ("hora_estudio", pa.string()),
    ("precision_hora", pa.string()),
])

_SCHEMA_ECO_MEDIDAS = pa.schema([
    ("id_paciente", pa.string()),
    ("id_episodio", pa.string()),
    ("id_medico_informante", pa.string()),
    ("anio", pa.int64()),
    ("fecha_estudio", pa.string()),
    ("nombre", pa.string()),
    ("valor", pa.string()),
    ("unidad", pa.string()),
    ("hora_estudio", pa.string()),
    ("precision_hora", pa.string()),
])

_SCHEMA_ECO_TEXTO = pa.schema([
    ("id_paciente", pa.string()),
    ("id_episodio", pa.string()),
    ("anio", pa.int64()),
    ("fecha_estudio", pa.string()),
    ("seccion", pa.string()),
    ("texto", pa.string()),
    ("hora_estudio", pa.string()),
    ("precision_hora", pa.string()),
])


class EscritorParquet:
    """Exporta lotes de `RegistroAnonimizado` a Parquet particionado por `tipo_documento/año`."""

    def __init__(self, directorio_base: Path) -> None:
        self._directorio_base = Path(directorio_base)

    def escribir(self, registros: Sequence[RegistroAnonimizado]) -> None:
        registros = self._deduplicar_por_clave_documento(registros)
        laboratorio = [r for r in registros if r.tipo_documento is TipoDocumento.LABORATORIO]
        ecg = [r for r in registros if r.tipo_documento is TipoDocumento.ECG]
        eco = [r for r in registros if r.tipo_documento is TipoDocumento.ECOCARDIOGRAMA]

        conocidos = len(laboratorio) + len(ecg) + len(eco)
        if conocidos != len(registros):
            tipos_desconocidos = {
                r.tipo_documento
                for r in registros
                if r.tipo_documento not in (TipoDocumento.LABORATORIO, TipoDocumento.ECG, TipoDocumento.ECOCARDIOGRAMA)
            }
            raise ValueError(f"tipo_documento no soportado por EscritorParquet: {tipos_desconocidos!r}")

        if laboratorio:
            self._escribir_dataset(
                self._directorio_base / "laboratorio", self._filas_laboratorio(laboratorio), _SCHEMA_LABORATORIO
            )
        if ecg:
            self._escribir_dataset(self._directorio_base / "ecg", self._filas_ecg(ecg), _SCHEMA_ECG)
        if eco:
            self._escribir_dataset(
                self._directorio_base / "eco_medidas", self._filas_eco_medidas(eco), _SCHEMA_ECO_MEDIDAS
            )
            self._escribir_dataset(
                self._directorio_base / "eco_texto", self._filas_eco_texto(eco), _SCHEMA_ECO_TEXTO
            )

    @staticmethod
    def _deduplicar_por_clave_documento(
        registros: Sequence[RegistroAnonimizado],
    ) -> list[RegistroAnonimizado]:
        """Descarta repeticiones del mismo documento dentro del lote recibido.

        Mismo criterio NULL-no-colisiona que Postgres (design.md, decisión 2):
        los registros con `clave_documento is None` no participan de la
        dedup -- se conservan todos, sin excepción.
        """
        vistos: set[str] = set()
        resultado: list[RegistroAnonimizado] = []
        for registro in registros:
            if registro.clave_documento is None:
                resultado.append(registro)
                continue
            if registro.clave_documento in vistos:
                continue
            vistos.add(registro.clave_documento)
            resultado.append(registro)
        return resultado

    @staticmethod
    def _escribir_dataset(raiz: Path, filas: list[dict], schema: pa.Schema | None = None) -> None:
        tabla = pa.Table.from_pylist(filas, schema=schema)
        pq.write_to_dataset(tabla, root_path=str(raiz), partition_cols=["anio"])

    @staticmethod
    def _filas_laboratorio(registros: list[RegistroAnonimizado]) -> list[dict]:
        filas: list[dict] = []
        for registro in registros:
            contenido: ContenidoLaboratorioSalida = registro.contenido
            for resultado in contenido.resultados:
                filas.append(
                    {
                        "id_paciente": registro.id_paciente,
                        "id_episodio": registro.id_episodio,
                        "id_medico": contenido.id_medico,
                        "anio": registro.fecha_estudio.year,
                        "fecha_estudio": registro.fecha_estudio.isoformat(),
                        "analito": resultado.analito,
                        "seccion": resultado.seccion,
                        "valor_num": resultado.valor_num,
                        "valor_texto": resultado.valor_texto,
                        "unidad": resultado.unidad,
                        "ref_min": resultado.ref_min,
                        "ref_max": resultado.ref_max,
                        "hora_estudio": (
                            registro.hora_estudio.isoformat() if registro.hora_estudio is not None else None
                        ),
                        "precision_hora": registro.precision_hora.value,
                    }
                )
        return filas

    @staticmethod
    def _filas_ecg(registros: list[RegistroAnonimizado]) -> list[dict]:
        filas: list[dict] = []
        for registro in registros:
            contenido: ContenidoEcgSalida = registro.contenido
            filas.append(
                {
                    "id_paciente": registro.id_paciente,
                    "id_episodio": registro.id_episodio,
                    "id_medico": contenido.id_medico,
                    "anio": registro.fecha_estudio.year,
                    "fecha_estudio": registro.fecha_estudio.isoformat(),
                    "vent_rate": contenido.vent_rate,
                    "pr_interval": contenido.pr_interval,
                    "qrs_duration": contenido.qrs_duration,
                    "qt_qtc": contenido.qt_qtc,
                    "ejes": contenido.ejes,
                    "hora_estudio": (
                        registro.hora_estudio.isoformat() if registro.hora_estudio is not None else None
                    ),
                    "precision_hora": registro.precision_hora.value,
                }
            )
        return filas

    @staticmethod
    def _filas_eco_medidas(registros: list[RegistroAnonimizado]) -> list[dict]:
        filas: list[dict] = []
        for registro in registros:
            contenido: ContenidoEcoSalida = registro.contenido
            for medida in contenido.medidas:
                filas.append(
                    {
                        "id_paciente": registro.id_paciente,
                        "id_episodio": registro.id_episodio,
                        "id_medico_informante": contenido.id_medico_informante,
                        "anio": registro.fecha_estudio.year,
                        "fecha_estudio": registro.fecha_estudio.isoformat(),
                        "nombre": medida.nombre,
                        "valor": medida.valor,
                        "unidad": medida.unidad,
                        "hora_estudio": (
                            registro.hora_estudio.isoformat() if registro.hora_estudio is not None else None
                        ),
                        "precision_hora": registro.precision_hora.value,
                    }
                )
        return filas

    @staticmethod
    def _filas_eco_texto(registros: list[RegistroAnonimizado]) -> list[dict]:
        filas: list[dict] = []
        for registro in registros:
            contenido: ContenidoEcoSalida = registro.contenido
            for seccion in contenido.secciones_texto:
                filas.append(
                    {
                        "id_paciente": registro.id_paciente,
                        "id_episodio": registro.id_episodio,
                        "anio": registro.fecha_estudio.year,
                        "fecha_estudio": registro.fecha_estudio.isoformat(),
                        "seccion": seccion.nombre,
                        "texto": seccion.texto,
                        "hora_estudio": (
                            registro.hora_estudio.isoformat() if registro.hora_estudio is not None else None
                        ),
                        "precision_hora": registro.precision_hora.value,
                    }
                )
        return filas

    def escribir_episodio(self, registros: Sequence[RegistroAnonimizado]) -> None:
        """Escribe la proyección analítica completa del episodio, de una sola vez.

        Recibe la SECUENCIA COMPLETA de documentos del episodio (spec
        `escritura-idempotente`, Requisito 4) -- no un registro por
        llamada: la versión anterior escribía uno a la vez con
        `write_table` + `replace`, y como los tres documentos de un
        episodio comparten `id_episodio`, cada llamada sobrescribía a la
        anterior y sobrevivía solo el último documento. Esta versión arma
        la tabla entera (una fila por documento) y hace un único
        `write_table` + `replace` atómico.
        """
        if not registros:
            raise ValueError("escribir_episodio requiere al menos un registro")
        id_episodio = registros[0].id_episodio
        destino = self._directorio_base / "episodios" / f"{id_episodio}.parquet"
        destino.parent.mkdir(parents=True, exist_ok=True)
        tabla = pa.Table.from_pylist([
            {
                "id_paciente": registro.id_paciente,
                "id_episodio": registro.id_episodio,
                "fecha_estudio": registro.fecha_estudio.isoformat(),
                "tipo_documento": registro.tipo_documento.value,
                "version_esquema": registro.version_esquema,
                # Reconciliación contra `estudio.clave_documento` en Postgres
                # sin re-derivar todo el corpus (design.md, "se mantiene").
                "clave_documento": registro.clave_documento,
            }
            for registro in registros
        ])
        temporal = destino.with_suffix(".tmp")
        pq.write_table(tabla, temporal)
        temporal.replace(destino)
