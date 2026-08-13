"""Puerto de salida para clasificar y extraer una familia documental."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from ingesta_clinica.dominio.extraccion import ResultadoExtraccion


@dataclass(frozen=True)
class ResultadoClasificacionFamilia:
    """Resultado efímero de la clasificación y extracción de una familia."""

    es_laboratorio: bool
    codigo_rechazo: str | None
    procedencia: Mapping[str, int] | None
    extraccion: ResultadoExtraccion | None


class PuertoSalidaClasificacionFamilia(Protocol):
    """Abstracción de salida para clasificar contenido efímero."""

    def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
        """Clasifica el contenido y devuelve sólo metadatos técnicos efímeros."""
        raise NotImplementedError
