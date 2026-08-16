"""Fixtures compartidas de la suite de integración/E2E (Fase 11).

`motor` es de scope `session` (no `module`, a diferencia de
`tests/pii/test_motor.py`/`tests/observabilidad/test_bitacora_segura.py`):
acá se comparte entre los 4 módulos de `tests/integracion/`, así que cargar
spaCy una sola vez para toda la carpeta evita pagar ese costo 4 veces.
"""

from __future__ import annotations

import pytest

from anonimizacion.pii.motor import MotorPii


@pytest.fixture(scope="session")
def motor() -> MotorPii:
    return MotorPii()
