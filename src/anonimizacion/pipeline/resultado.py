"""Resultado de procesar UN documento: unión discriminada éxito/fallo, cada rama con sólo los
campos que tiene sentido que tenga. `resumen_trazable()` es la única superficie de log: whitelist
fija de metadata no sensible, nunca un dump genérico de la excepción o del documento."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from anonimizacion.dominio.errores import ErrorDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento


@dataclass(frozen=True)
class ExitoDocumento:
    """Un documento procesado y emitido con éxito."""

    id_documento: str
    tipo_documento: TipoDocumento
    id_paciente: str
    id_episodio: str
    timestamp: datetime

    def resumen_trazable(self) -> dict[str, Any]:
        """Whitelist fija para el log de trazabilidad del lote -- nunca PII."""
        return {
            "id_documento": self.id_documento,
            "tipo_documento": self.tipo_documento.value,
            "estado": "exito",
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class FalloDocumento:
    """Un documento que terminó en cuarentena; `error` ya es metadata sin PII."""

    id_documento: str
    error: ErrorDocumento
    timestamp: datetime

    def resumen_trazable(self) -> dict[str, Any]:
        """Whitelist fija para el log de trazabilidad del lote -- nunca PII."""
        return {
            "id_documento": self.id_documento,
            "etapa": self.error.etapa,
            "codigo": self.error.codigo.value,
            "estado": "fallo",
            "timestamp": self.timestamp.isoformat(),
        }


ResultadoDocumento = ExitoDocumento | FalloDocumento
