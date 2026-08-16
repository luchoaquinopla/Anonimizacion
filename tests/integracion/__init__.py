"""Tests de integración/E2E (Fase 11, tasks.md 11.2-11.5, spec `batch-processing`/`anonymized-output`).

Ejercitan `pipeline/ejecutor.py::EjecutorPipeline` de punta a punta contra
componentes REALES (extracción PyMuPDF, detección de tipo, parsers,
`MotorPii`/Presidio+spaCy, pseudonimización HMAC, linkage, `construir_registro`,
storage SQLite -- ver `tests/salida/test_migraciones.py`/`test_postgres.py`
para el precedente de usar SQLite en vez de un Postgres real en este entorno
de desarrollo). Los fakes de `tests/pipeline/test_ejecutor.py` (PR7) ya
cubren aislamiento de fallo/reintentos a nivel de unidad; estos tests
verifican el mismo comportamiento con los componentes reales conectados.
"""

from __future__ import annotations
