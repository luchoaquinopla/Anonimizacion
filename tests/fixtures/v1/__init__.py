"""Fixtures sintéticas versionadas por tipo de documento (tasks.md 11.1).

`v1` corresponde a `version_esquema=1`, la única versión de esquema que
emiten hoy los tres parsers (`parseo/laboratorio_general.py`,
`parseo/ecg_mortara.py`, `parseo/eco_doppler.py`). Si en el futuro aparece
un `version_esquema=2` con un layout distinto (evolución aditiva, mismo
principio que `EcgPayload.waveform` en design.md), sus fixtures van en un
paquete hermano `tests/fixtures/v2/`, sin tocar este -- así un test de
integración puede fijar contra qué versión de layout corre sin ambigüedad.
"""

from __future__ import annotations
