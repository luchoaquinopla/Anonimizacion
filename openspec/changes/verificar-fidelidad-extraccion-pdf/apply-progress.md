# Progreso de aplicación: verificar fidelidad de extracción desde PDF

**Modo:** TDD estricto
**Unidad:** PR 10 — corrección final Eco y evidencia auditable
**Rama:** `fix/reconciliacion-medidas-eco`
**Base:** `feat/pdf-extraction-reconciliation`

## Tareas completadas

- [x] 5.1 RED: asociación cruzada de medidas Eco en tabla de dos columnas.
- [x] 5.2 GREEN: selector específico por etiqueta de medida Eco.
- [x] 5.3 RED/GREEN: whitelist Eco declarativa para boilerplate no clínico.
- [x] 5.4 REFACTOR: evidencia TDD auditable por tarea.
- [x] 5.5 VERIFICAR: suite, cobertura y formato de informe.

## Evidencia del ciclo TDD

| Tarea | Archivos de prueba | Archivos de producción | Capa | Safety net | RED | GREEN | Triangulación | Refactor |
|---|---|---|---|---|---|---|---|---|
| 5.1 | `tests/reconciliacion/test_eco_doppler.py` | — | Unitaria | ✅ `pytest -q tests/reconciliacion/test_eco_doppler.py tests/reconciliacion/test_inventario.py` → 25 passed | ✅ Written; `test_emite_selector_especifico_por_etiqueta_en_tabla_de_dos_columnas` y `test_rechaza_medidas_iguales_asignadas_a_selectores_cruzados_en_dos_columnas` fallaron | ✅ Passed; `pytest -q tests/reconciliacion/test_eco_doppler.py tests/reconciliacion/test_inventario.py` → 28 passed | ✅ Tabla de dos columnas con dos etiquetas y valor igual; parser y asignación cruzada | ➖ No necesario |
| 5.2 | `tests/reconciliacion/test_eco_doppler.py` | `src/anonimizacion/dominio/referencias.py`, `src/anonimizacion/reconciliacion/base.py`, `src/anonimizacion/parseo/eco_doppler.py`, `src/anonimizacion/reconciliacion/eco_doppler.py` | Unitaria | ✅ 25 passed | ✅ Written; selector genérico emitido y selector específico rechazado | ✅ Passed; 28 passed | ✅ Selector `eco.medida.xx`/`eco.medida.yy` y cruce de referencias | ✅ Selector normalizado centralizado y sin valores |
| 5.3 | `tests/reconciliacion/test_inventario.py` | `src/anonimizacion/reconciliacion/eco_doppler.py` | Unitaria | ✅ 25 passed | ✅ Written; faltaba `es_texto_permitido` en Eco | ✅ Passed; 28 passed | ✅ Boilerplate permitido y fila clínica rechazada | ✅ Whitelist local e inmutable |
| 5.4 | `openspec/changes/verificar-fidelidad-extraccion-pdf/apply-progress.md` | — | Artefacto | N/A | ✅ Written; faltaba evidencia auditable | ✅ Passed; tabla con tarea, archivos, estados y comandos | ➖ Estructura única requerida | ✅ Sin duplicar contenido clínico |
| 5.5 | — | `openspec/changes/verificar-fidelidad-extraccion-pdf/verify-report.md`, `openspec/changes/verificar-fidelidad-extraccion-pdf/tasks.md` | Verificación | N/A | ✅ Written; `git diff --check main...HEAD` informó seis espacios finales ya presentes en `HEAD` | ✅ Passed; `pytest -q` → 342 passed; cobertura → 342 passed, 96%; `git diff --check` del árbol de trabajo limpio | ✅ Suite focalizada y completa | ✅ Espacios finales eliminados; al commitear, `main...HEAD` incorporará su eliminación |

## Resultado acumulado de esta unidad

- Suite focalizada: 28 passed.
- Suite completa: 342 passed.
- Cobertura: 96% total; ningún módulo modificado quedó debajo de 80%.
- Chequeo de formato: `git diff --check` limpio; `main...HEAD` conserva los espacios hasta crear el commit correctivo.

## Corrección P1 posterior: etiqueta Eco normalizada

| Alcance | Archivos | Safety net | RED | GREEN | Refactor |
|---|---|---|---|---|---|
| Asociación de etiqueta con espacio/puntuación | `tests/reconciliacion/test_eco_doppler.py`, `src/anonimizacion/reconciliacion/eco_doppler.py` | ✅ `pytest -q tests/reconciliacion/test_eco_doppler.py` → 19 passed | ✅ Written; `test_reconcilia_etiqueta_de_medida_con_espacio_y_puntuacion` falló con `valor_discrepante` | ✅ Passed; mismo comando → 20 passed | ✅ La asociación divide el valor esperado en el único prefijo cuya normalización genera el selector; `P. Posterior` coincide con `eco.medida.p.posterior` |

## Corrección P1 posterior: catálogo seguro de selectores Eco

| Alcance | Archivos | Safety net | RED | GREEN | Triangulación |
|---|---|---|---|---|---|
| Selector de etiqueta clínica u opaca | `tests/reconciliacion/test_normalizacion.py`, `tests/reconciliacion/test_eco_doppler.py`, `src/anonimizacion/dominio/referencias.py` | ✅ `pytest -q tests/reconciliacion/test_normalizacion.py tests/reconciliacion/test_eco_doppler.py` → 37 passed | ✅ Written; `test_selector_eco_usa_catalogo_clinico_y_opaca_etiquetas_arbitrarias` falló porque `JUAN PEREZ` generaba `eco.medida.juan.perez` | ✅ Passed; mismo comando → 38 passed | ✅ `P. Posterior` conserva `eco.medida.p.posterior`; `JUAN PEREZ` recibe `eco.medida.no_catalogada`; tabla cruzada usa AO/AI clínicos |
- No se modificaron valores clínicos, PII ni persistencia de cuarentena.
