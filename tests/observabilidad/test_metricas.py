"""Tests de `observabilidad/metricas.py` (tasks.md 10.2)."""

from __future__ import annotations

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.observabilidad.metricas import MetricasEnMemoria


def test_incrementa_documentos_procesados_por_tipo() -> None:
    metricas = MetricasEnMemoria()
    metricas.incrementar_documento_procesado(TipoDocumento.LABORATORIO)
    metricas.incrementar_documento_procesado(TipoDocumento.LABORATORIO)
    metricas.incrementar_documento_procesado(TipoDocumento.ECG)

    snapshot = metricas.snapshot()
    assert snapshot["documentos_procesados"] == {"laboratorio": 2, "ecg": 1}


def test_incrementa_fallos_por_codigo() -> None:
    metricas = MetricasEnMemoria()
    metricas.incrementar_fallo(CodigoErrorDocumento.TIPO_NO_RECONOCIDO)
    metricas.incrementar_fallo(CodigoErrorDocumento.TIPO_NO_RECONOCIDO)
    metricas.incrementar_fallo(CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA)

    snapshot = metricas.snapshot()
    assert snapshot["fallos"] == {"tipo_no_reconocido": 2, "clave_pii_no_resuelta": 1}


def test_observa_duraciones_por_etapa() -> None:
    metricas = MetricasEnMemoria()
    metricas.observar_duracion_ms("parseo", 12.5)
    metricas.observar_duracion_ms("parseo", 8.0)
    metricas.observar_duracion_ms("deteccion_pii", 30.0)

    snapshot = metricas.snapshot()
    assert snapshot["duraciones_ms"] == {"parseo": [12.5, 8.0], "deteccion_pii": [30.0]}


def test_snapshot_vacio_al_inicio() -> None:
    metricas = MetricasEnMemoria()
    snapshot = metricas.snapshot()
    assert snapshot == {"documentos_procesados": {}, "fallos": {}, "duraciones_ms": {}}


def test_snapshot_es_una_copia_no_una_referencia_viva() -> None:
    metricas = MetricasEnMemoria()
    metricas.incrementar_documento_procesado(TipoDocumento.ECG)
    snapshot_previo = metricas.snapshot()
    metricas.incrementar_documento_procesado(TipoDocumento.ECG)
    assert snapshot_previo["documentos_procesados"] == {"ecg": 1}
