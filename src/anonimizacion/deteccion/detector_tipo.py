"""`detectar_tipo`: clasifica un `TextoExtraido` según las firmas conocidas.
Nunca lanza: si ninguna firma coincide o dos empatan, devuelve `TIPO_NO_RECONOCIDO`."""

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
