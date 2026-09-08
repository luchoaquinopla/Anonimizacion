"""Lector compartido de fixtures de texto serializados por `esqueleto.py`.

`Esqueleto.formatear()` y `FixtureParseable.formatear()` (ver
`src/anonimizacion/esqueleto.py`) usan EXACTAMENTE el mismo formato de
serialización a propósito (encabezados `## pagina N (orden de dibujado)` /
`## pagina N (orden geometrico)`): permite reconstruir un `TextoExtraido`
desde cualquiera de los dos tipos de fixture con un único lector, en vez de
duplicar esta lógica de reagrupado en cada archivo de test que consume un
fixture versionado (`tests/deteccion/test_centinela_esqueletos.py`,
`tests/deteccion/test_centinela_fixtures_parseables.py` y el test de
regresión de parseo bajo `tests/fixtures/parseables/`).
"""

from __future__ import annotations

import re
from pathlib import Path

from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

_ENCABEZADO_PAGINA = re.compile(r"^## pagina \d+ \((orden de dibujado|orden geometrico)\)$")


def leer_texto_extraido_de_fixture(ruta: Path) -> TextoExtraido:
    """Reconstruye un `TextoExtraido` a partir de un fixture versionado
    (esqueleto enmascarado o fixture parseable, mismo formato serializado).

    Operación inversa de `Esqueleto.formatear()`/`FixtureParseable.formatear()`:
    reagrupa las líneas de cada bloque `## pagina N (orden de ...)` en
    páginas, respetando ambas representaciones (`paginas`/`paginas_ordenadas`)
    que `TextoExtraido` expone.
    """
    texto = ruta.read_text(encoding="utf-8")
    paginas_dibujado: list[str] = []
    paginas_geometrico: list[str] = []
    modo: str | None = None
    buffer: list[str] = []

    def _cerrar_pagina_actual() -> None:
        if modo == "orden de dibujado":
            paginas_dibujado.append("\n".join(buffer))
        elif modo == "orden geometrico":
            paginas_geometrico.append("\n".join(buffer))

    for linea in texto.splitlines():
        coincidencia = _ENCABEZADO_PAGINA.match(linea)
        if coincidencia:
            _cerrar_pagina_actual()
            modo = coincidencia.group(1)
            buffer = []
            continue
        if linea.startswith("#") and modo is None:
            continue  # comentarios de cabecera del fixture, antes de la primera pagina
        if modo is not None:
            buffer.append(linea)
    _cerrar_pagina_actual()

    assert paginas_dibujado, f"'{ruta.name}' no trae ninguna pagina en orden de dibujado"
    assert paginas_geometrico, f"'{ruta.name}' no trae ninguna pagina en orden geometrico"
    return TextoExtraido(paginas=tuple(paginas_dibujado), paginas_ordenadas=tuple(paginas_geometrico))
