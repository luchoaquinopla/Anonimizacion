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


class EscritorParquet:
    """Exporta lotes de `RegistroAnonimizado` a Parquet particionado por `tipo_documento/año`."""

    def __init__(self, directorio_base: Path) -> None:
        self._directorio_base = Path(directorio_base)

    def escribir(self, registros: Sequence[RegistroAnonimizado]) -> None:
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
            self._escribir_dataset(self._directorio_base / "laboratorio", self._filas_laboratorio(laboratorio))
        if ecg:
            self._escribir_dataset(self._directorio_base / "ecg", self._filas_ecg(ecg))
        if eco:
            self._escribir_dataset(self._directorio_base / "eco_medidas", self._filas_eco_medidas(eco))
            self._escribir_dataset(self._directorio_base / "eco_texto", self._filas_eco_texto(eco))

    @staticmethod
    def _escribir_dataset(raiz: Path, filas: list[dict]) -> None:
        tabla = pa.Table.from_pylist(filas)
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
                    }
                )
        return filas

    def escribir_episodio(self, registro: RegistroAnonimizado) -> None:
        """Mantiene una única proyección analítica vigente por episodio."""
        destino = self._directorio_base / "episodios" / f"{registro.id_episodio}.parquet"
        destino.parent.mkdir(parents=True, exist_ok=True)
        tabla = pa.Table.from_pylist([
            {
                "id_paciente": registro.id_paciente,
                "id_episodio": registro.id_episodio,
                "fecha_estudio": registro.fecha_estudio.isoformat(),
                "tipo_documento": registro.tipo_documento.value,
                "version_esquema": registro.version_esquema,
            }
        ])
        temporal = destino.with_suffix(".tmp")
        pq.write_table(tabla, temporal)
        temporal.replace(destino)
