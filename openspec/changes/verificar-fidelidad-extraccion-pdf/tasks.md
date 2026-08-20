# Tasks: Verificar fidelidad de extracción desde PDF

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 1,620–2,150; 260–380 restantes |
| 400-line budget risk | High (cambio total); Medium (PR correctivo) |
| Chained PRs recommended | Yes |
| Suggested split | PR 5 ECG → PR 6 laboratorio → PR 7 eco → PR 8 pipeline → PR 9 asociación → PR 10 corrección final → PR 11 procedencia multipágina |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | Cobertura ECG | PR 5 | Base feature; completado. |
| 2 | Cobertura laboratorio | PR 6 | Base feature; completado. |
| 3 | Cobertura eco | PR 7 | Base feature; completado. |
| 4 | Integración y cuarentena | PR 8 | Base feature; completado. |
| 5 | Asociación etiqueta→valor | PR 9 | Correctivo separado; base `feat/pdf-extraction-reconciliation`. |
| 6 | Corrección final Eco y evidencia TDD | PR 10 | Base `feat/pdf-extraction-reconciliation`; cambio autocontenido y menor a 400 líneas. |
| 7 | Procedencia real multipágina y tipo seguro | PR 11 | Base `feat/pdf-extraction-reconciliation`; correctivo TDD, 260–380 líneas. |

## Phase 1: Contratos y normalización

- [x] 1.1 RED: pruebas de igualdad, coma/punto, espacios, fechas y rechazos en `tests/reconciliacion/test_normalizacion.py`.
- [x] 1.2 GREEN: crear `reconciliacion/{__init__,base,normalizacion}.py` con `ReferenciaCampo` y `ReconciliadorDocumento`.
- [x] 1.3 RED/GREEN: ampliar `tests/dominio/test_{modelos,errores}.py` y `dominio/{modelos,errores}.py` con fuentes y códigos seguros.
- [x] 1.4 REFACTOR: impedir texto, PII, valores y huellas persistibles en referencias/excepciones.

## Phase 2: Estrategias y procedencia

- [x] 2.1 RED/GREEN: crear pruebas y estrategia ECG en `tests/reconciliacion/test_ecg_mortara.py` y `reconciliacion/ecg_mortara.py`.
- [x] 2.2 RED/GREEN: cubrir filas repetidas de laboratorio en `tests/reconciliacion/test_laboratorio_general.py` y su estrategia/parser.
- [x] 2.3 RED/GREEN: cubrir medidas, texto y firma de eco en `tests/reconciliacion/test_eco_doppler.py` y su estrategia/parser.
- [x] 2.4 REFACTOR: crear `reconciliacion/registro.py`, actualizar `parseo/registro.py` y rechazar referencias sin destino.

## Phase 3: Cobertura completa (PR 5–8)

- [x] 3.1 RED/GREEN: añadir `HallazgoCobertura`, cruce modelo↔inventario y códigos en `reconciliacion/{base,inventario,_comun}.py`.
- [x] 3.2 RED/GREEN: inventariar headers/medidas ECG y rechazar una medida omitida.
- [x] 3.3 RED/GREEN: inventariar filas clínicas por sección/ordinal de laboratorio y alinear su parser.
- [x] 3.4 RED/GREEN: inventariar medidas/secciones de eco por página/ordinal y alinear sus referencias.
- [x] 3.5 RED/GREEN: ejecutar reconciliación tras `parsear`, cuarentena segura y pruebas de aislamiento en `pipeline/`, `salida/` y `tests/integracion/`.

## Phase 4: Asociación exacta campo–valor (PR 9 correctivo)

- [x] 4.1 RED: añadir en `tests/reconciliacion/test_{ecg_mortara,eco_doppler}.py` asignaciones cruzadas: ambos valores existen una vez, pero pertenecen a etiquetas distintas; debe fallar.
- [x] 4.2 GREEN: actualizar `reconciliacion/_comun.py` y las estrategias ECG/eco para usar `ReferenciaCampo.selector` como evidencia anclada etiqueta→valor, no solo como whitelist.
- [x] 4.3 REFACTOR: conservar normalizaciones permitidas, verificar errores seguros y ejecutar la suite completa; publicar PR 9 separado contra `feat/pdf-extraction-reconciliation`.

## Phase 5: Corrección final y evidencia auditable (PR 10)

- [x] 5.1 RED: en `tests/reconciliacion/test_eco_doppler.py`, añadir dos medidas Eco —incluida tabla de dos columnas y valor igual— con asignación cruzada; debe fallar por etiqueta→valor incorrecta.
- [x] 5.2 GREEN: en `src/anonimizacion/{parseo,reconciliacion}/eco_doppler.py`, emitir y consumir un selector específico por etiqueta de medida; prohibir la validación de valor aislado.
- [x] 5.3 RED/GREEN: en `tests/reconciliacion/test_inventario.py`, verificar que texto desconocido/no clínico permitido no exige destino y que un patrón clínico reconocido sin destino falla; ajustar whitelist solo si el test lo exige.
- [x] 5.4 REFACTOR: registrar por cada tarea RED→GREEN en `openspec/changes/verificar-fidelidad-extraccion-pdf/apply-progress.md`, con `✅ Written`, `✅ Passed`, archivos y comando de prueba.
- [x] 5.5 VERIFICAR: eliminar espacios finales de `verify-report.md`, ejecutar `pytest -q`, `git diff --check main...HEAD` y cobertura; publicar PR 10 contra `feat/pdf-extraction-reconciliation`.

## Phase 6: Procedencia multipágina y cuarentena segura (PR 11 correctivo)

- [x] 6.1 RED: en `tests/{parseo,reconciliacion}/test_laboratorio_general.py`, crear dos páginas con el mismo resultado y exigir que cada fila conserve la página donde se encontró, sin búsqueda global posterior.
- [x] 6.2 GREEN/REFACTOR: en `src/anonimizacion/parseo/laboratorio_general.py` y `reconciliacion/laboratorio_general.py`, propagar la página desde la fila detectada hasta `ReferenciaCampo` e inventario.
- [x] 6.3 RED: en `tests/{parseo,reconciliacion}/test_eco_doppler.py`, repetir medidas, texto y firma en páginas distintas; exigir que referencias e inventario mantengan la página de origen.
- [x] 6.4 GREEN/REFACTOR: en `src/anonimizacion/{parseo,reconciliacion}/eco_doppler.py`, fijar la página al detectar cada medida, sección y firma; no reconstruirla por coincidencia global.
- [x] 6.5 RED/GREEN: en `tests/{parseo,reconciliacion}/test_eco_doppler.py`, distinguir subsección `PADRE - HIJA` de dos líneas consecutivas; ajustar inventario/parser sin fusionar texto clínico no equivalente.
- [x] 6.6 RED/GREEN: en `tests/{dominio,salida,pipeline}/test_{errores,cuarentena,ejecutor}.py` y `tests/salida/test_migraciones.py`, exigir `tipo_documento` seguro en `ErrorDocumento`, cuarentena y ORM; agregar migración posterior a `0002` sin PII.
- [x] 6.7 REFACTOR/VERIFICAR: ejecutar `pytest -q`, migraciones y `git diff --check`; registrar RED→GREEN por tarea en `apply-progress.md` y publicar PR 11 contra `feat/pdf-extraction-reconciliation`.
