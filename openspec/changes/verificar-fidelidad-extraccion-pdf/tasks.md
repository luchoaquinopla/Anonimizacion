# Tasks: Verificar fidelidad de extracción desde PDF

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 1,620–2,150; 120–200 restantes |
| 400-line budget risk | High (cambio total); Low (PR correctivo) |
| Chained PRs recommended | Yes |
| Suggested split | PR 5 ECG → PR 6 laboratorio → PR 7 eco → PR 8 pipeline → PR 9 asociación |
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
