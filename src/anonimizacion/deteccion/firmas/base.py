"""`Firma`: marcadores textuales que identifican un tipo de documento.

Es la pieza de datos del Strategy de detección: `detector_tipo.detectar_tipo`
itera sobre una colección de `Firma` genéricamente (un solo loop), en vez de
un `if/elif` por cada tipo conocido (ver spec `document-type-detection`,
requirement "Despacho vía Strategy sin if/elif monolítico"). Agregar un
layout nuevo es agregar una `Firma` a la colección, no tocar el detector.
"""

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

        `detectar_tipo` compara el puntaje de todas las firmas entre sí y se
        queda con la de mayor evidencia, en vez de la primera que matchea
        (ver spec `document-type-detection`). Defecto medido que motiva esto:
        la firma de ecocardiograma reconocía un documento real por un solo
        marcador genérico de 4 caracteres ("S.C.") porque `coincide` usaba
        `any()` -- alcanzaba con uno solo, sin importar cuán específico fuera.
        """
        return sum(1 for marcador in self.marcadores if marcador in texto_normalizado)

    def coincide(self, texto_normalizado: str) -> bool:
        """`texto_normalizado` ya debe estar en mayúsculas (ver `detectar_tipo`)."""
        return self.puntaje(texto_normalizado) > 0
