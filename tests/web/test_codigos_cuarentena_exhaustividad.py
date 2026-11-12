"""Exhaustividad de `EXPLICACION_POR_CODIGO` (Entrega 3, Requisito 2 de la
spec `poder-deteccion-tests`).

Todo `CodigoErrorDocumento` que pueda llegar a cuarentena debe tener una
entrada en `EXPLICACION_POR_CODIGO`. Sin este test, un código nuevo sin
traducción cae en el "último recurso" de cada llamador (mostrar el código
crudo) sin que nadie lo note -- el médico ve `cobertura_incompleta` en vez
de una frase legible.

`CAMPO_NO_EXTRAIDO` se excluye explícitamente: por su propio docstring
(`dominio/errores.py:92-103`) nunca se lanza vía `ErrorParseo` y nunca
produce fila en `cuarentena`.
"""

from __future__ import annotations

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.web.codigos_cuarentena import EXPLICACION_POR_CODIGO

# Motivo por código excluido de la exhaustividad (nunca producen fila en
# `cuarentena`, ver docstring del módulo).
_CODIGOS_EXCLUIDOS_DE_CUARENTENA_CON_MOTIVO: dict[CodigoErrorDocumento, str] = {
    CodigoErrorDocumento.CAMPO_NO_EXTRAIDO: (
        "viaja como marca de completitud sobre un documento publicado, "
        "nunca como ErrorParseo -- nunca llega a cuarentena"
    ),
}


def test_todo_codigo_que_llega_a_cuarentena_tiene_explicacion() -> None:
    excluidos = {codigo.value for codigo in _CODIGOS_EXCLUIDOS_DE_CUARENTENA_CON_MOTIVO}

    sin_explicacion = {
        codigo.value
        for codigo in CodigoErrorDocumento
        if codigo.value not in excluidos and codigo.value not in EXPLICACION_POR_CODIGO
    }

    assert not sin_explicacion, f"Códigos de cuarentena sin entrada en EXPLICACION_POR_CODIGO: {sin_explicacion}"
