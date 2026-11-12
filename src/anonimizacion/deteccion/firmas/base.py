"""`Firma`: marcadores textuales que identifican un tipo de documento.
Pieza de datos del Strategy de detección: agregar un layout es agregar una `Firma`."""

from __future__ import annotations

from dataclasses import dataclass

from anonimizacion.dominio.tipos_documento import TipoDocumento


@dataclass(frozen=True)
class Firma:
    """Un tipo de documento y los marcadores que, si aparecen, lo identifican."""

    tipo: TipoDocumento
    marcadores: tuple[str, ...]

    def puntaje(self, texto_normalizado: str) -> int:
        """Cantidad de marcadores de esta firma que aparecen en el texto.
        `detectar_tipo` compara el puntaje de todas las firmas y gana la de mayor evidencia."""
        return sum(1 for marcador in self.marcadores if marcador in texto_normalizado)

    def coincide(self, texto_normalizado: str) -> bool:
        """`texto_normalizado` ya debe estar en mayúsculas (ver `detectar_tipo`)."""
        return self.puntaje(texto_normalizado) > 0
