# Tasks: Verificar fidelidad de extracción desde PDF

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 850–1,150 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → contratos; PR 2 → estrategias; PR 3 → integración/cuarentena |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | Contratos, errores y normalización | PR 1 | Tests unitarios incluidos; rollback aislado. |
| 2 | Reglas y referencias de los tres parsers | PR 2 | Depende de PR 1; tests sintéticos por Strategy. |
| 3 | Pipeline, cuarentena y migración | PR 3 | Depende de PR 2; pruebas de integración y persistencia. |

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

## Phase 3: Integración segura

- [ ] 3.1 RED: ampliar `tests/pipeline/test_{etapas,ejecutor}.py`: aprobado llega a PII; rechazo no llama PII, claves, vínculo ni salida.
- [ ] 3.2 GREEN: modificar `pipeline/{etapas,ejecutor}.py` para reconciliar tras parseo; errores no reintentables deben aislarse antes de `resueltos`.
- [ ] 3.3 RED/GREEN: ampliar `tests/salida/test_{cuarentena,migraciones}.py`, `salida/{cuarentena,modelos_orm}.py` y migración Alembic con whitelist `campo`/`pagina` sin evidencia, valor, PII ni huella.
- [ ] 3.4 Verificar `tests/integracion/test_lote_aislamiento.py` con un sintético rechazado y dos aprobados; ejecutar `pytest` por unidad y la suite completa.
