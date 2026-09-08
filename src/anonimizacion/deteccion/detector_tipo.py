"""`detectar_tipo`: clasifica un `TextoExtraido` según las firmas conocidas.

Spec `document-type-detection`: nunca lanza — si ninguna firma coincide,
devuelve `TIPO_NO_RECONOCIDO`. Esa decisión es intencional: el pipeline no
debe abortar el lote por un layout desconocido, el documento sigue su camino
hacia cuarentena en una etapa posterior, no acá.

Despacho por puntaje, no por "la primera firma que matchea": defecto medido
-- con la firma vieja de ecocardiograma (ver `firmas/eco_doppler.py`), un
documento real matcheaba por un solo marcador genérico de 4 caracteres
("S.C.") y ya alcanzaba para clasificarlo, porque `Firma.coincide` usaba
`any()` y `detectar_tipo` devolvía la primera firma que matcheara sin
comparar contra las demás. Ahora se evalúan TODAS las firmas, se compara
`Firma.puntaje` (cantidad de marcadores que aparecen) y gana la de mayor
evidencia. Si dos firmas empatan con puntaje > 0, es ambigüedad real -- el
texto se parece igual de bien a dos layouts distintos -- y se devuelve
`TIPO_NO_RECONOCIDO` en vez de arriesgar una clasificación falsa: que el
pipeline diga "no sé" es preferible a que diga mal (va a cuarentena, no se
descarta).

No hay un umbral mínimo de marcadores (p. ej. "al menos 2"): se evaluó y
algunos fixtures sintéticos vigentes del repo (`tests/fixtures/v1/
documentos.py`, usado por varios tests de integración) sólo declaran un
marcador de ecocardiograma reconocible tal cual quedó la firma legada. Un
umbral mínimo los rompería sin necesidad -- el puntaje ya resuelve el
problema real (evidencia comparativa entre firmas), un piso arbitrario no
agrega nada más que fixtures rotos.
"""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

from .firmas import FIRMAS


def detectar_tipo(texto: TextoExtraido) -> TipoDocumento:
    texto_normalizado = texto.texto_completo.upper()
    puntajes = [(firma.puntaje(texto_normalizado), firma.tipo) for firma in FIRMAS]
    puntaje_maximo = max(puntaje for puntaje, _ in puntajes)
    if puntaje_maximo == 0:
        return TipoDocumento.TIPO_NO_RECONOCIDO
    ganadores = {tipo for puntaje, tipo in puntajes if puntaje == puntaje_maximo}
    if len(ganadores) > 1:
        return TipoDocumento.TIPO_NO_RECONOCIDO
    return next(iter(ganadores))
