Estado: completado. RED intencional verificado.

Resumen ejecutivo: configuré `pytest` sólo para pruebas, creé `.venv` local e ignorado, y españolicé los contratos/placeholder de `ingesta_clinica`. No se creó código de producción ni se modificó `NUL` u OpenSpec.

Artefactos:
- `.venv/` con `pytest 9.1.1`, ignorado por Git.
- Dependencia de test en `pyproject.toml`.
- Tres pruebas RED bajo `tests/`.

Archivos modificados:
- `.gitignore`
- `AGENTS.md`
- `pyproject.toml`
- `tests/test_contrato_adaptador_laboratorio.py`
- `tests/test_contrato_privacidad.py`
- `tests/test_contratos_ingesta.py`

Comandos/resultados:
- `.venv/Scripts/python.exe -m pip install pytest`: exitoso.
- `.venv/Scripts/python.exe -m py_compile ...`: exitoso.
- `.venv/Scripts/python.exe -m pytest`: RED esperado; 3 errores de colección por `ModuleNotFoundError: No module named 'ingesta_clinica'`.
- `git diff --check`: exitoso, sin errores de whitespace.
- `git diff --cached --name-only`: vacío.

Riesgos:
- El árbol ya tenía cambios ajenos sin stage, incluyendo OpenSpec, `.pi/` y `NUL`; no fueron modificados.
- Los contratos seguirán RED hasta implementar `src/ingesta_clinica`.

Próximo paso recomendado: implementar la PR GREEN en un cambio posterior, creando `src/ingesta_clinica` según estos contratos.

Resolución de skill: leído `work-unit-commits`; no se realizó commit por instrucción explícita.