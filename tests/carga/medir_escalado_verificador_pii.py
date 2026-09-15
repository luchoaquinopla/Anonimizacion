"""Mide el crecimiento del verificador lineal de PII con N y 10N documentos.

**Qué mide**: SOLO `pii/verificador_lineal.py::contar_coincidencias_pii` sobre
registros sintéticos (nunca PII real) -- no ejercita el pipeline ni PDFs, es
un banco de medición de escala, no un test de corrección (la corrección la
cubre `tests/pii/test_verificador_lineal.py` contra el oráculo cuadrático).

No forma parte de la suite de `pytest`: un umbral de tiempo en CI es frágil
(hardware compartido, ruido de otros procesos). Se ejecuta directo:

    python tests/carga/medir_escalado_verificador_pii.py [--n 1000]

Si el crecimiento es ~lineal, el tiempo de 10N debe ser ~10x el de N (no
~100x, que sería la firma de la versión cuadrática que este módulo reemplaza).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_RAIZ_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RAIZ_REPO / "src"))
sys.path.insert(0, str(_RAIZ_REPO))

from tests.fixtures.verificador_pii import generar_semilla  # noqa: E402
from tests.pii.verificador_lineal import contar_coincidencias_pii  # noqa: E402


def _medir(cantidad_documentos: int) -> float:
    # ~10 valores de PII por documento, mismo orden de magnitud que el corpus
    # piloto real (ver `tests/corpus_sintetico/test_pipeline_piloto.py`: 520
    # valores para 120 registros).
    registros, valores = generar_semilla(
        20260915, cantidad_registros=cantidad_documentos, cantidad_valores=max(10, cantidad_documentos // 12)
    )
    inicio = time.perf_counter()
    contar_coincidencias_pii(registros, valores)
    return time.perf_counter() - inicio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=1000, help="cantidad base de documentos sintéticos")
    args = parser.parse_args()

    n, diez_n = args.n, args.n * 10
    segundos_n = _medir(n)
    segundos_diez_n = _medir(diez_n)
    razon = segundos_diez_n / segundos_n if segundos_n else float("inf")

    print(f"{'documentos':>12} | {'segundos':>10}")
    print(f"{n:>12} | {segundos_n:>10.4f}")
    print(f"{diez_n:>12} | {segundos_diez_n:>10.4f}")
    print(f"razón 10N/N: {razon:.2f}x (lineal ideal: 10.00x; cuadrático: ~100x)")


if __name__ == "__main__":
    main()
