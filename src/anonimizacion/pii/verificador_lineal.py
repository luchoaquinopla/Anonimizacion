"""Verificador de fuga de PII, O(texto + patrones) vía Aho-Corasick puro.

Reemplaza a la versión cuadrática que vivía en
`tests/fixtures/corpus_piloto.py::contar_coincidencias_pii` (ahora conservada
sólo como oráculo de test en `tests/fixtures/verificador_pii.py`): esa versión
comparaba cada valor de PII contra cada registro con `in`, es decir
O(registros × valores × longitud), inviable para auditar un dataset completo
de ~100k documentos.

Semántica exacta a preservar (decisión 7 del diseño): por cada registro se
suma la multiplicidad de cada valor de PII PRESENTE como subcadena (no la
cantidad de ocurrencias dentro del texto -- una vez que aparece, cuenta según
cuántas veces ese valor está repetido en la lista de valores a buscar). El
valor vacío es subcadena de cualquier texto, así que cuenta en todos los
registros.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable, Sequence

_RAIZ = 0


class _Automata:
    """Trie con enlaces de fallo y `hijos` extendido a función total (goto)."""

    __slots__ = ("hijos", "fallo", "salida")

    def __init__(self) -> None:
        self.hijos: dict[str, int] = {}
        self.fallo: int = _RAIZ
        self.salida: set[int] = set()


def _construir_automata(patrones: Sequence[str]) -> list[_Automata]:
    nodos = [_Automata()]
    for indice, patron in enumerate(patrones):
        actual = _RAIZ
        for caracter in patron:
            actual = nodos[actual].hijos.setdefault(caracter, _agregar_nodo(nodos))
        nodos[actual].salida.add(indice)
    _enlazar_fallos_y_extender_goto(nodos)
    return nodos


def _agregar_nodo(nodos: list[_Automata]) -> int:
    nodos.append(_Automata())
    return len(nodos) - 1


def _enlazar_fallos_y_extender_goto(nodos: list[_Automata]) -> None:
    # BFS por nivel: al llegar a cada nodo, su fallo ya tiene el `goto` total
    # calculado, así que la búsqueda nunca retrocede por enlaces de fallo.
    cola: deque[int] = deque(nodos[_RAIZ].hijos.values())
    while cola:
        actual = cola.popleft()
        nodo = nodos[actual]
        for caracter, hijo in list(nodo.hijos.items()):
            cola.append(hijo)
            fallo_hijo = nodos[nodo.fallo].hijos.get(caracter, _RAIZ)
            nodos[hijo].fallo = fallo_hijo
            nodos[hijo].salida |= nodos[fallo_hijo].salida
        for caracter, destino in nodos[nodo.fallo].hijos.items():
            nodo.hijos.setdefault(caracter, destino)


def _patrones_presentes(nodos: list[_Automata], texto: str) -> set[int]:
    encontrados: set[int] = set()
    actual = _RAIZ
    for caracter in texto:
        actual = nodos[actual].hijos.get(caracter, _RAIZ)
        if nodos[actual].salida:
            encontrados |= nodos[actual].salida
    return encontrados


def contar_coincidencias_pii(registros: Iterable[object], valores_pii: Sequence[str]) -> int:
    """Cuenta coincidencias de `valores_pii` (con multiplicidad) dentro de `registros`.

    Misma semántica que la versión cuadrática original: cada `registro` se
    serializa con `repr(...).casefold()`, cada `valor` con `.casefold()`.
    """
    multiplicidades = Counter(valor.casefold() for valor in valores_pii)
    vacios = multiplicidades.pop("", 0)
    patrones = list(multiplicidades)
    registros = list(registros)
    total = vacios * len(registros)
    if not patrones:
        return total
    nodos = _construir_automata(patrones)
    for registro in registros:
        texto = repr(registro).casefold()
        for indice in _patrones_presentes(nodos, texto):
            total += multiplicidades[patrones[indice]]
    return total
