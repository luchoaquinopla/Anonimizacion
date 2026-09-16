"""Auditoría reproducible de PII sobre el dataset EXPORTADO.

Cierra la tarea 4.3 de `senal-ecg-y-dataset-vinculado` y, con ella, la tarea
5.2 de `operacion-segura-y-escalable` (auditar el dataset contra PII): genera
un corpus sintético con PII conocida, lo procesa de punta a punta por el
pipeline real (mismo camino de producción que `tests/fixtures/corpus_piloto.py`,
pero contra una base real -- no en memoria -- para poder EXPORTARLA), exporta
el dataset con `exportar_dataset` y pasa el verificador lineal de PII sobre
TODO el contenido exportado: los 4 Parquet (todas las columnas, incluidos los
JSON de `adicionales` y las listas de la señal de ECG) y `manifiesto.json`.
Exige CERO coincidencias contra los valores de PII sintéticos conocidos
(nombre, DNI, fecha de nacimiento, y el resto de lo que registra
`generar_corpus_clinico`).

Decisión: vive en la suite normal (no en `tests/carga/`). Es una prueba de
CORRECTITUD -- un invariante de seguridad que debe sostenerse siempre, no una
medición de rendimiento/escala -- corre contra SQLite en memoria en menos de
un segundo. El volumen (1k/10k documentos) ya lo cubren los escalones de
`tests/carga/`, que miden throughput, no fuga de PII fila por fila.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa

from anonimizacion.dominio.modelos import ClavesPaciente
from anonimizacion.ingesta.fuente import FuenteLocal, HuellasEnMemoria
from anonimizacion.pipeline.ejecutor import ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.exportacion import NOMBRE_MANIFIESTO, exportar_dataset
from anonimizacion.salida.modelos_orm import Base
from anonimizacion.trabajadores.tareas import construir_fabrica_ejecutor
from tests.fixtures.pdf_sintetico import generar_corpus_clinico
from tests.pii.verificador_lineal import contar_coincidencias_pii


class _MotorPiiOffline:
    """Mismo doble que `corpus_piloto.py`: el motor real carga spaCy, y este
    test no necesita ejercitar la detección de PII de Presidio, sólo que la
    salida EXPORTADA no contenga los valores sintéticos conocidos."""

    def evaluar_ids_internos(self, ids_internos):
        return ()

    def detectar(self, texto):
        return ()


class _CuarentenaMemoria:
    def __init__(self) -> None:
        self.errores: list[object] = []

    def registrar(self, error: object) -> None:
        self.errores.append(error)


def _resolver_claves(_identidad, _pepper, _resolutor, *, id_documento: str, etapa: str) -> ClavesPaciente:
    id_caso = id_documento.split("__", maxsplit=1)[0]
    return ClavesPaciente(id_paciente=f"pac-{id_caso}", id_alt_paciente=None, version_clave=1)


def _generar_corpus_y_procesar(directorio: Path, *, semilla: int) -> tuple[sa.Engine, list[str]]:
    """Genera 4 episodios completos (ecg+laboratorio+ecocardiograma) con PII
    sintética distinta por caso y los procesa por el pipeline real contra una
    base SQLite real (no un doble en memoria) para poder exportarlos después."""
    entrada = directorio / "entrada"
    generados = directorio / "generados"
    entrada.mkdir(parents=True)
    valores_pii: list[str] = []
    for indice in range(4):
        prefijo = f"caso-{indice:03d}"
        base = date(2024, 2, 1) + timedelta(days=indice * 15)
        fechas = {"ecg": base, "laboratorio": base, "ecocardiograma": base}
        corpus = generar_corpus_clinico(
            generados / prefijo, semilla=semilla + indice,
            fechas_estudio=fechas, registrar_pii=valores_pii.extend,
        )
        for documento in corpus.documentos:
            shutil.copyfile(documento.ruta, entrada / f"{prefijo}__{documento.tipo}.pdf")

    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inventario = tuple(
        FuenteLocal(
            raices=(directorio,),
            directorio=entrada,
            tope_bytes=10 * 1024 * 1024,
            huellas=HuellasEnMemoria(),
            cuarentena=_CuarentenaMemoria(),
        ).listar()
    )
    items = tuple(ItemLote(Path(artefacto.uri).stem, artefacto) for artefacto in inventario)
    cuarentena = _CuarentenaMemoria()
    ejecutor = construir_fabrica_ejecutor(
        raices=(directorio,),
        resolutor=object(),
        motor=_MotorPiiOffline(),
        pepper=b"pepper-auditoria-exportacion-sintetico",
        destino=EscritorPostgres(engine),
        cuarentena=cuarentena,
        dormir=lambda _segundos: None,
        resolver_claves=_resolver_claves,
    )()
    resultados = ejecutor.procesar_lote(items)
    publicados = sum(isinstance(resultado, ExitoDocumento) for resultado in resultados)
    assert publicados == len(items), (
        "la auditoria asume que el corpus sintetico completo se publica sin "
        f"cuarentena -- {publicados}/{len(items)} publicados, "
        f"cuarentena: {cuarentena.errores}"
    )
    return engine, valores_pii


def _filas_exportadas(directorio_export: Path) -> list[dict[str, object]]:
    filas: list[dict[str, object]] = []
    for nombre in ("episodios", "ecg", "laboratorio", "eco"):
        tabla = pq.read_table(directorio_export / f"{nombre}.parquet")
        filas.extend(tabla.to_pylist())
    return filas


def _registros_a_auditar(directorio_export: Path) -> list[object]:
    manifiesto = json.loads((directorio_export / NOMBRE_MANIFIESTO).read_text(encoding="utf-8"))
    return [*_filas_exportadas(directorio_export), manifiesto]


@pytest.fixture()
def _dataset_exportado(tmp_path: Path) -> tuple[Path, list[str]]:
    engine, valores_pii = _generar_corpus_y_procesar(tmp_path / "corpus", semilla=20260915)
    directorio_export = tmp_path / "export"
    exportar_dataset(engine, directorio_export)
    engine.dispose()
    return directorio_export, [valor for valor in valores_pii if valor]


def test_auditoria_de_pii_sobre_el_dataset_exportado_no_encuentra_coincidencias(
    _dataset_exportado: tuple[Path, list[str]],
) -> None:
    """Criterio de éxito de la propuesta: 0 coincidencias de nombre, DNI y
    fecha de nacimiento en TODO el contenido exportado (4 Parquet completos,
    incluidos `adicionales_json` y las listas de `muestras_uv`/`mascara` de la
    señal de ECG, más `manifiesto.json`)."""
    directorio_export, valores_pii = _dataset_exportado
    assert valores_pii, (
        "el corpus sintetico debe registrar PII conocida -- si esta lista "
        "esta vacia la auditoria es vacua (siempre pasaria)"
    )

    coincidencias = contar_coincidencias_pii(_registros_a_auditar(directorio_export), valores_pii)

    assert coincidencias == 0, (
        f"el dataset exportado contiene {coincidencias} coincidencia(s) de PII "
        "sintetica -- ver tasks.md 4.3 y spec `exportacion-dataset-vinculado`"
    )


def test_auditoria_de_pii_es_falsable_detecta_una_fuga_inyectada_a_proposito(
    _dataset_exportado: tuple[Path, list[str]],
) -> None:
    """Demuestra que la auditoría de arriba no es vacua: un verificador roto
    que siempre devolviera 0 pasaría la auditoría igual sin este test. Se
    inyecta a propósito uno de los valores de PII conocidos en una copia de
    una fila REAL ya exportada (mismo objeto que produce `_filas_exportadas`,
    no un objeto nuevo inventado) y se confirma que la MISMA función de
    auditoría usada arriba lo detecta."""
    directorio_export, valores_pii = _dataset_exportado
    valor_inyectado = valores_pii[0]

    registros = _registros_a_auditar(directorio_export)
    assert contar_coincidencias_pii(registros, [valor_inyectado]) == 0, (
        "precondicion: antes de contaminar, ese valor no debe aparecer en la salida"
    )

    indice_afectado = next(
        indice
        for indice, registro in enumerate(registros)
        if isinstance(registro, dict) and "adicionales_json" in registro
    )
    fila_contaminada = dict(registros[indice_afectado])
    fila_contaminada["adicionales_json"] = json.dumps({"fuga_de_prueba": valor_inyectado})
    registros_contaminados = list(registros)
    registros_contaminados[indice_afectado] = fila_contaminada

    coincidencias = contar_coincidencias_pii(registros_contaminados, [valor_inyectado])

    assert coincidencias > 0, (
        "la auditoria no detecto una fuga de PII inyectada a proposito -- "
        "el verificador esta roto o la auditoria de arriba es vacua"
    )
