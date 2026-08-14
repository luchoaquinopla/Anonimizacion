status: RED completado.

executive_summary: Agregué 5 pruebas RED para el contrato futuro de bloques sintéticos de laboratorio, sin cambios de producción.

artifacts:
- `tests/test_contrato_bloques_laboratorio.py`

next_recommended: Implementar únicamente GREEN de `extraer_bloques` en la siguiente fase aprobada.

risks:
- Las pruebas fallan intencionalmente porque `AdaptadorFamiliaLaboratorio` no expone `extraer_bloques`.
- Hay archivos no rastreados preexistentes en `.pi/` y `NUL`; no fueron modificados.

skill_resolution: Leído `work-unit-commits/SKILL.md`.

changed files:
- Nuevo: `tests/test_contrato_bloques_laboratorio.py`

commands/results:
- Suite existente antes de crear pruebas: 16 passed.
- Pruebas RED nuevas: 5 failed por `AttributeError` esperado.
- `git diff --check`: passed.
- `git diff --no-index --check /dev/null tests/test_contrato_bloques_laboratorio.py`: sin errores de espacios (exit 1 esperado para un archivo nuevo).
- Sin archivos en staging.

explicit RED evidence: las cinco pruebas fallan con `AttributeError: 'AdaptadorFamiliaLaboratorio' object has no attribute 'extraer_bloques'`.