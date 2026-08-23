"""Entrada local del escalón de 10.000 PDFs; no forma parte de CI."""

import json
from pathlib import Path

from tests.carga.ejecutar_corpus import (
    DUPLICADOS_CARGA_10000,
    ORACULO_CARGA_10000,
    PLAN_CARGA_10000,
    ejecutar_cli,
)


if __name__ == "__main__":
    resultado = ejecutar_cli(
        Path("tmp/carga_10000"),
        semilla=20260823,
        tipos_caso=PLAN_CARGA_10000,
        duplicados=DUPLICADOS_CARGA_10000,
        oraculo=ORACULO_CARGA_10000,
    )
    print(json.dumps(resultado.como_dict(), indent=2))
