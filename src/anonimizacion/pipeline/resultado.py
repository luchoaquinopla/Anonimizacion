"""Resultado de procesar UN documento: unión discriminada éxito/fallo (tasks.md 8.1).

Spec `batch-processing`, requirement "Trazabilidad sin PII": cada resultado
(éxito o fallo) tiene que poder loguearse con SOLO metadata no sensible (id
de documento, tipo, estado, timestamp). `resumen_trazable()` es la ÚNICA
superficie pensada para eso: por construcción devuelve un `dict` con un
conjunto fijo y acotado de claves -- mismo principio que `ErrorDocumento`
(`dominio/errores.py`): campos explícitos, nunca un dump genérico de la
excepción o del documento. No hace falta un módulo de bitácora separado acá
(eso es `observabilidad/bitacora_segura.py`, Fase 10, todavía no construida)
-- alcanza con que lo que este módulo expone ya sea imposible de que
contenga PII.

`ExitoDocumento`/`FalloDocumento` son dos dataclasses distintas unidas por
`ResultadoDocumento` (no una excepción atrapada en silencio, no un booleano
`ok: bool` con campos opcionales): quien recibe un `ResultadoDocumento` hace
`isinstance` para bifurcar, y el tipo de cada rama solo tiene los campos que
tiene sentido que tenga (un éxito no puede "tener" un `error` a medio
llenar; un fallo no puede "tener" un `id_paciente` a medias).
"""

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
