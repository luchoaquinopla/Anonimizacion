"""El reloj del banco no debe medir trabajo que produccion no hace.

Estos tests inyectan una demora artificial en la generacion del corpus y en
la verificacion de PII -- ninguna de las dos existe en produccion -- y
comprueban que esa demora aparece en su propia fase pero NO contamina el
tiempo de procesamiento, que es el unico numero que el banco debe usar para
extrapolar rendimiento.
"""

from __future__ import annotations

import time

from tests.fixtures import corpus_piloto

_DEMORA_SEGUNDOS = 0.5
_MARGEN_SEGUNDOS = 0.25


def test_generacion_del_corpus_no_contamina_el_tiempo_de_procesamiento(
    tmp_path, monkeypatch
) -> None:
    original = corpus_piloto._crear_entrada

    def _crear_entrada_lenta(*args, **kwargs):
        time.sleep(_DEMORA_SEGUNDOS)
        return original(*args, **kwargs)

    monkeypatch.setattr(corpus_piloto, "_crear_entrada", _crear_entrada_lenta)

    resultado = corpus_piloto.ejecutar_corpus_sintetico(
        tmp_path, semilla=1, tipos_caso=("completo",), duplicados=0
    )

    assert resultado.tiempo_preparacion_segundos >= _DEMORA_SEGUNDOS
    assert resultado.tiempo_procesamiento_segundos < _MARGEN_SEGUNDOS


def test_verificacion_de_pii_no_contamina_el_tiempo_de_procesamiento(
    tmp_path, monkeypatch
) -> None:
    original = corpus_piloto.contar_coincidencias_pii

    def _contar_coincidencias_pii_lento(*args, **kwargs):
        time.sleep(_DEMORA_SEGUNDOS)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        corpus_piloto, "contar_coincidencias_pii", _contar_coincidencias_pii_lento
    )

    resultado = corpus_piloto.ejecutar_corpus_sintetico(
        tmp_path, semilla=1, tipos_caso=("completo",), duplicados=0
    )

    assert resultado.tiempo_verificacion_segundos >= _DEMORA_SEGUNDOS
    assert resultado.tiempo_procesamiento_segundos < _MARGEN_SEGUNDOS
