"""Métricas del pipeline, en memoria de proceso (tasks.md 10.2).

Módulo deliberadamente simple: contadores de documentos/fallos y duraciones
observadas por etapa, todo en memoria del worker. Integrar un backend real
de métricas (Prometheus, StatsD, OpenTelemetry, ...) es una decisión de
infraestructura de producción que design.md no toma explícitamente -- no se
inventa acá una elección de backend sin decisión de por medio. En cambio, se
define `ColectorMetricas` como contrato mínimo: un backend real puede
implementarlo sin que el resto del pipeline (que solo depende del Protocol)
se entere del cambio.

Los nombres de los campos que expone `snapshot()` son consistentes con las
whitelists ya usadas en `pipeline/resultado.py` y `observabilidad/bitacora_segura.py`
(`tipo_documento`, `codigo`, `etapa`) -- reusa los mismos `Enum`/valores de
dominio, no inventa un vocabulario propio.
"""

from __future__ import annotations

import threading
from collections import Counter, defaultdict
from typing import Protocol

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento


class ColectorMetricas(Protocol):
    """Contrato mínimo que cualquier backend de métricas (real o en memoria) cumple."""

    def incrementar_documento_procesado(self, tipo_documento: TipoDocumento) -> None: ...

    def incrementar_fallo(self, codigo: CodigoErrorDocumento) -> None: ...

    def observar_duracion_ms(self, etapa: str, duracion_ms: float) -> None: ...


class MetricasEnMemoria:
    """Implementación por defecto: contadores/listas en memoria de proceso.

    Thread-safe vía un lock simple (los workers de Celery pueden correr
    varias tareas concurrentes en el mismo proceso según el pool elegido).
    No persiste entre reinicios del worker -- para eso hace falta un backend
    real, ver docstring del módulo.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._documentos_procesados: Counter[str] = Counter()
        self._fallos: Counter[str] = Counter()
        self._duraciones_ms: dict[str, list[float]] = defaultdict(list)

    def incrementar_documento_procesado(self, tipo_documento: TipoDocumento) -> None:
        with self._lock:
            self._documentos_procesados[tipo_documento.value] += 1

    def incrementar_fallo(self, codigo: CodigoErrorDocumento) -> None:
        with self._lock:
            self._fallos[codigo.value] += 1

    def observar_duracion_ms(self, etapa: str, duracion_ms: float) -> None:
        with self._lock:
            self._duraciones_ms[etapa].append(duracion_ms)

    def snapshot(self) -> dict[str, object]:
        """Foto instantánea de las métricas acumuladas hasta el momento."""
        with self._lock:
            return {
                "documentos_procesados": dict(self._documentos_procesados),
                "fallos": dict(self._fallos),
                "duraciones_ms": {
                    etapa: list(valores) for etapa, valores in self._duraciones_ms.items()
                },
            }
