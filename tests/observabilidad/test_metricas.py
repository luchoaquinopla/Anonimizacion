"""Tests de `observabilidad/metricas.py` (tasks.md 10.2)."""

from __future__ import annotations

import pytest

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


def test_resumen_operacional_expone_solo_contadores_agregados() -> None:
    metricas = MetricasEnMemoria()
    metricas.incrementar_documento_procesado(TipoDocumento.LABORATORIO)
    metricas.incrementar_fallo(CodigoErrorDocumento.COBERTURA_INCOMPLETA)
    metricas.observar_duracion_ms("parseo", 10.0)
    metricas.observar_duracion_ms("parseo", 20.0)

    resumen = metricas.resumen_operacional()

    assert resumen == {
        "documentos_procesados": {"laboratorio": 1},
        "fallos_por_codigo": {"cobertura_incompleta": 1},
        "duraciones_ms": {"parseo": {"cantidad": 2, "promedio": 15.0}},
    }


def test_resumen_operacional_no_acepta_etapas_con_pii() -> None:
    metricas = MetricasEnMemoria()

    with pytest.raises(ValueError, match="etapa no admitida"):
        metricas.observar_duracion_ms("paciente Juan Pérez", 12.0)

    assert metricas.resumen_operacional()["duraciones_ms"] == {}
