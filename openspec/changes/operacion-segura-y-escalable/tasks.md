# Tasks: operación segura y escalable

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 2.000–3.500 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | 1 dominio/persistencia → 2 orquestación/salida → 3 portal/operación → 4 corpus/eco |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|---|---|---|---|
| 1 | Corridas durables | PR 1 | Estados, repositorio, migración y pruebas |
| 2 | Episodios y bundles | PR 2 | Depende de PR 1; coordina y publica |
| 3 | Portal y servicio | PR 3 | Depende de PR 1; operación intranet |
| 4 | Corpus y eco | PR 4 | Puede avanzar tras contratos de PR 1 |

## Phase 1: Corridas durables

- [x] 1.1 **RED**: crear `tests/dominio/test_corridas.py` para transiciones, huella duplicada y reanudación.
- [x] 1.2 **GREEN**: añadir `src/anonimizacion/dominio/corridas.py` y `estados_corrida.py` con estados/versionado.
- [x] 1.3 **RED/GREEN**: extender `src/anonimizacion/salida/modelos_orm.py` y migraciones con corrida/documento; probar persistencia en `tests/salida/test_migraciones.py`.
- [x] 1.4 **REFACTOR**: extraer repositorio de corridas en `src/anonimizacion/ingesta/repositorio_corridas.py`; eliminar duplicación de estado.

## Phase 2: Ingesta, coordinación y salida

- [x] 2.1 **RED/GREEN**: implementar `InventariadorDocumentos` en `ingesta/fuente.py`: raíces permitidas, extensión/tamaño y huella idempotente; probar rutas rechazadas.
- [x] 2.2 **RED/GREEN**: crear `pipeline/coordinador_episodios.py` y pruebas de ventanas, empates, faltantes y cierre de corrida.
- [x] 2.3 **RED/GREEN**: adaptar `trabajadores/tareas.py` para persistir extracción mínima/completa sin publicar; probar reinicio sin duplicados.
- [x] 2.4 **RED/GREEN**: añadir `salida/publicador_bundles.py` y completar `salida/destinos/parquet.py`; probar escritura atómica, manifiesto sin PII y una fila vigente.
- [x] 2.5 **REFACTOR**: integrar coordinador, reconciliadores y `pipeline/ejecutor.py`; añadir E2E de cuarentena previa a anonimización/publicación.

## Phase 3: Portal y operación institucional

- [ ] 3.1 **RED/GREEN**: crear `src/anonimizacion/web/` con rutas internas de crear/consultar/reintentar corrida; probar que no acepta PDFs ni secretos.
- [ ] 3.2 **RED/GREEN**: exponer contadores agregados desde `observabilidad/metricas.py` y códigos seguros desde `bitacora_segura.py`.
- [ ] 3.3 **RED/GREEN**: configurar cola, concurrencia y reintentos en `trabajadores/app.py`; probar límites y fallo recuperable.
- [ ] 3.4 documentar instalación como servicio y variables protegidas en `deploy/` y `README.md`; incluir permisos, backups, retención y rollback.

## Phase 4: Corpus, eco y carga

- [ ] 4.1 **RED/GREEN**: ampliar `tests/fixtures/pdf_sintetico.py` con plantillas ECG/laboratorio/eco, semilla y oráculo; probar repetibilidad y cero red/PII real.
- [ ] 4.2 **RED/GREEN**: crear `tests/corpus_sintetico/test_pipeline_masivo.py` para válidos, ambiguos, faltantes, corruptos, fechas límite y ausencia de PII.
- [ ] 4.3 crear `tests/carga/ejecutar_corpus.py` con escalones 1k/10k/100k y métricas de tiempo, memoria, reintentos y duplicados; no ejecutar 100k en CI.
- [ ] 4.4 **RED**: registrar metadata segura de eco en `observabilidad/diagnostico_seguro.py` y fixture mínima que reproduce la cuarentena.
- [ ] 4.5 **GREEN/REFACTOR**: corregir `parseo/eco_doppler.py` sólo si 4.4 confirma causa; mantener variantes desconocidas en cuarentena.
- [ ] 4.6 actualizar `docs/pipeline.md` y la arquitectura/bitácora de Obsidian al cerrar cada work unit.

## Phase 5: Verificación

- [ ] 5.1 Ejecutar `pytest` y las integraciones PostgreSQL/cola; registrar cobertura de escenarios SDD.
- [ ] 5.2 Auditar dataset, logs, manifiestos y diagnósticos contra PII; verificar separación de originales/cuarentena.
