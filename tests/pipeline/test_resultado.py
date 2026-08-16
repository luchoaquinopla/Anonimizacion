"""Tests de `pipeline/resultado.py` -- unión discriminada éxito/fallo (tasks.md 8.1)."""

from __future__ import annotations

from datetime import datetime, timezone

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pipeline.resultado import ExitoDocumento, FalloDocumento


def _ahora() -> datetime:
    return datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def test_exito_documento_expone_metadata_no_sensible() -> None:
    exito = ExitoDocumento(
        id_documento="doc-1",
        tipo_documento=TipoDocumento.LABORATORIO,
        id_paciente="abc123",
        id_episodio="ep-1",
        timestamp=_ahora(),
    )
    assert exito.id_documento == "doc-1"
    assert exito.tipo_documento is TipoDocumento.LABORATORIO


def test_exito_documento_resumen_trazable_solo_tiene_campos_whitelist() -> None:
    exito = ExitoDocumento(
        id_documento="doc-1",
        tipo_documento=TipoDocumento.LABORATORIO,
        id_paciente="abc123",
        id_episodio="ep-1",
        timestamp=_ahora(),
    )
    resumen = exito.resumen_trazable()
    assert set(resumen.keys()) == {"id_documento", "tipo_documento", "estado", "timestamp"}
    assert resumen["estado"] == "exito"
    assert resumen["tipo_documento"] == "laboratorio"
    # nunca el id_paciente/id_episodio -- aunque no son PII cruda (son HMAC),
    # la whitelist de trazabilidad del lote solo declara id/tipo/estado/timestamp
    # (spec batch-processing, "Trazabilidad sin PII")
    assert "id_paciente" not in resumen
    assert "id_episodio" not in resumen


def test_fallo_documento_resumen_trazable_no_expone_mensaje_crudo() -> None:
    error = ErrorDocumento(
        id_documento="doc-2", etapa="parseo", codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO
    )
    fallo = FalloDocumento(id_documento="doc-2", error=error, timestamp=_ahora())
    resumen = fallo.resumen_trazable()
    assert resumen == {
        "id_documento": "doc-2",
        "etapa": "parseo",
        "codigo": "parseo_incompleto",
        "estado": "fallo",
        "timestamp": _ahora().isoformat(),
    }


def test_exito_y_fallo_son_tipos_distintos_no_una_excepcion_silenciada() -> None:
    # unión discriminada real: isinstance distingue los casos, no un flag booleano
    error = ErrorDocumento(
        id_documento="doc-3", etapa="deteccion", codigo=CodigoErrorDocumento.TIPO_NO_RECONOCIDO
    )
    fallo = FalloDocumento(id_documento="doc-3", error=error, timestamp=_ahora())
    exito = ExitoDocumento(
        id_documento="doc-4",
        tipo_documento=TipoDocumento.ECG,
        id_paciente="x",
        id_episodio="y",
        timestamp=_ahora(),
    )
    assert isinstance(fallo, FalloDocumento)
    assert not isinstance(fallo, ExitoDocumento)
    assert isinstance(exito, ExitoDocumento)
    assert not isinstance(exito, FalloDocumento)
