# Tasks: Verificar fidelidad de extracción desde PDF

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 1,500–1,950; 700–950 restantes |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 5 → cobertura base+ECG; PR 6 → laboratorio; PR 7 → eco; PR 8 → pipeline |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | Contrato y cobertura ECG | PR 5 | Base `feat/pdf-extraction-reconciliation`; tests. |
| 2 | Inventario y cobertura de laboratorio | PR 6 | Base rama PR 5; cardinalidad/ordinal. |
| 3 | Inventario y cobertura de eco | PR 7 | Base rama PR 6; medidas y secciones. |
| 4 | Bloqueo, cuarentena e integración | PR 8 | Base rama PR 7; suite completa. |

## Phase 1: Contratos y normalización

- [x] 1.1 RED: crear `tests/reconciliacion/test_normalizacion.py` para igualdad, coma/punto, espacios, fecha ISO y rechazos de unidad, signo o precisión.
- [x] 1.2 GREEN: crear `src/anonimizacion/reconciliacion/{__init__,base,normalizacion}.py` con `ReferenciaCampo`, reglas puras y `ReconciliadorDocumento`.
- [x] 1.3 RED/GREEN: ampliar `tests/dominio/test_{modelos,errores}.py` y `src/anonimizacion/dominio/{modelos,errores}.py` con `fuentes`, etapa y códigos seguros.
- [x] 1.4 REFACTOR: validar que referencias y excepciones no admitan texto, PII, valores ni huellas persistibles.

## Phase 2: Estrategias y procedencia

- [x] 2.1 RED: crear `tests/reconciliacion/test_ecg_mortara.py` para coincidencia, ausencia, ambigüedad y discrepancia ECG.
- [x] 2.2 GREEN: crear `reconciliacion/ecg_mortara.py` y modificar `parseo/ecg_mortara.py` para emitir referencias por header y medida.
- [x] 2.3 RED/GREEN: cubrir laboratorio en `tests/reconciliacion/test_laboratorio_general.py`, `reconciliacion/laboratorio_general.py` y `parseo/laboratorio_general.py`, incluidas filas repetidas por ordinal.
- [x] 2.4 RED/GREEN: cubrir eco en `tests/reconciliacion/test_eco_doppler.py`, `reconciliacion/eco_doppler.py` y `parseo/eco_doppler.py`, incluidas medidas, texto y firma.
- [x] 2.5 REFACTOR: crear `reconciliacion/registro.py` y actualizar `parseo/registro.py`; rechazar referencias sin destino y no persistir HMAC.

## Phase 3: Cobertura base y ECG (PR 5)

- [x] 3.1 RED: añadir pruebas de `HallazgoCobertura`, claves duplicadas/desordenadas y whitelist en `tests/reconciliacion/test_inventario.py`.
- [x] 3.2 GREEN: ampliar `reconciliacion/{base,inventario,_comun}.py` con contrato seguro, cruce modelo↔inventario y códigos de cobertura.
- [x] 3.3 RED/GREEN: inventariar headers/medidas ECG en `reconciliacion/ecg_mortara.py`; una omitida debe fallar sin valor.

## Phase 4: Colecciones de laboratorio y eco (PR 6–7)

- [x] 4.1 RED/GREEN: inventariar filas clínicas por sección/ordinal en `reconciliacion/laboratorio_general.py`; probar repetida, omitida y boilerplate permitido.
- [x] 4.2 REFACTOR: emitir ordinales coherentes desde `parseo/laboratorio_general.py`, sin reutilizar el resultado parseado como inventario.
- [ ] 4.3 RED/GREEN: inventariar medidas y secciones por página/ordinal en `reconciliacion/eco_doppler.py`; probar duplicación y omisión.
- [ ] 4.4 REFACTOR: alinear referencias de `parseo/eco_doppler.py` y validar asociación selector-etiqueta-valor, no mera presencia.

## Phase 5: Integración segura (PR 8)

- [ ] 5.1 RED: ampliar `tests/pipeline/test_{etapas,ejecutor}.py`: cobertura fallida no invoca PII, claves, vínculo ni salida.
- [ ] 5.2 GREEN: ejecutar inventario y reconciliación tras `parsear` en `pipeline/{etapas,ejecutor}.py`; aislar como no reintentable.
- [ ] 5.3 RED/GREEN: verificar `salida/cuarentena.py` y `tests/salida/test_cuarentena.py`: solo metadata segura.
- [ ] 5.4 Verificar omisiones sintéticas ECG/laboratorio/eco en `tests/integracion/test_lote_aislamiento.py`; ejecutar `pytest` y suite completa.
