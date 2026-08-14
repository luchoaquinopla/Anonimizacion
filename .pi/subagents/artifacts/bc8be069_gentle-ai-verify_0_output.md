## Verificación

Comando ejecutado:

- `.venv/Scripts/python.exe -m pytest`
- Resultado: **25 passed in 0.07s**, incluidos los 9 casos de `tests/test_contrato_bloques_laboratorio.py`.

Evidencia revisada:

- `src/ingesta_clinica/adaptadores/salida/laboratorio.py`
- `tests/test_contrato_bloques_laboratorio.py`
- `tests/test_contrato_adaptador_laboratorio.py`
- `src/ingesta_clinica/aplicacion/puertos/{entrada,salida}.py`

Confirmado:

- Orden variable: salida determinista y campos ordenados por código.
- Sin filas: rechazo explícito `TABLA_LABORATORIO_SIN_FILAS_RESULTADO`.
- Filas incompletas: rechazo seguro sin extracción ni procedencia.
- Candidatos conflictivos: resolución como `ambiguo`.
- Estructuras no compatibles: rechazo seguro.
- Procedencia: únicamente `numero_pagina` e `indice_bloque`.
- Privacidad: resultados no conservan texto fuente ni valores clínicos; el adaptador tampoco mantiene estado persistente.
- Capa de aplicación: no contiene imports del adaptador concreto.

**Hallazgos:** sin bloqueantes ni defectos observados.

**Riesgo residual:** no se ejecutó cobertura instrumental (`pytest --cov`); “cobertura” se confirma por escenarios contractuales y pruebas pasantes. Tampoco se inspeccionó el estado de staging porque no fue un comando autorizado.