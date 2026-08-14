# Tareas: Pipeline de extracción y anonimización de PDFs clínicos

## Review Workload Forecast

| Campo | Valor |
|---|---|
| Líneas estimadas | 3500-5000+ (9 fases, ~15 módulos nuevos, esquema SQL, Celery, motor PII) |
| Riesgo de presupuesto 400 líneas | High |
| PRs encadenados recomendados | Yes |
| Split sugerido | PR1→PR9 (ver Work Units) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Objetivo | PR | Notas |
|---|---|---|---|
| 1 | Fase 0+1: runner de tests + dominio | PR1 | Base de todo; sin dependencias |
| 2 | Fase 2+3: ingest, extracción PyMuPDF, detección de tipo | PR2 | Depende de PR1 |
| 3 | Fase 4: parsing (Protocol+registry+3 parsers) | PR3 | Depende de PR2; parsers independientes entre sí |
| 4 | Fase 5: detección de PII | PR4 | Depende de PR1 (dominio); paralelo a PR3 |
| 5 | Fase 6: pseudonimización + linkage ±7d | PR5 | Depende de PR4 |
| 6 | Fase 7: emit/storage (Postgres+Parquet+cuarentena) | PR6 | Depende de PR3+PR5; incluye migraciones SQL |
| 7 | Fase 8+9: pipeline runner + workers Celery | PR7 | Depende de PR6 |
| 8 | Fase 10: observability | PR8 | Depende de PR1; puede ir en paralelo temprano |
| 9 | Fase 11: integración/E2E con fixtures sintéticas | PR9 | Depende de todo lo anterior |

## Fase 0: Infraestructura de Tests

- [ ] 0.1 Elegir pytest como test runner; agregar a `pyproject.toml` (`pytest`, `pytest-cov`)
- [ ] 0.2 Configurar `openspec/config.yaml`: `apply.tdd: true`, `apply.test_command: "pytest"`, `verify.test_command: "pytest"`
- [ ] 0.3 Crear `tests/` con `conftest.py` y estructura `tests/fixtures/` (sintéticas)

## Fase 1: Dominio (Foundation)

- [ ] 1.1 Crear `pyproject.toml` con stack: pymupdf, presidio-analyzer, spacy, pydantic, celery, redis, sqlalchemy, pyarrow
- [ ] 1.2 Test + impl `src/anonimizacion/domain/doc_types.py` (`DocType` enum)
- [ ] 1.3 Test + impl `src/anonimizacion/domain/errors.py` (`DocumentError`, `ParseError` tipados)
- [ ] 1.4 Test + impl `src/anonimizacion/domain/models.py`: `ParsedDocument`, `RawIdentity` (SecretStr, `__repr__` redactado), `PatientKeys`, `AnonymizedRecord`

## Fase 2: Ingest + Extracción

- [ ] 2.1 Test + impl `src/anonimizacion/ingest/artifact.py` (`RawArtifact`: uri+sha256+format)
- [ ] 2.2 Test + impl `src/anonimizacion/ingest/source.py` (`ArtifactSource` filesystem)
- [ ] 2.3 Test + impl `src/anonimizacion/extraction/pymupdf_text.py` — spec pdf-text-extraction: texto nativo sin OCR, fallo explícito en PDF corrupto (fixtures lab/ECG sintéticas)

## Fase 3: Detección de Tipo de Documento

- [ ] 3.1 Test + impl `src/anonimizacion/detection/signatures/` (marcadores por tipo) y `type_detector.py` — spec document-type-detection: clasificación + `TYPE_UNRECOGNIZED` sin abortar

## Fase 4: Parsing

- [ ] 4.1 Test + impl `src/anonimizacion/parsing/base.py` (`DocumentParser` Protocol) + `registry.py`
- [ ] 4.2 Test + impl `parsing/lab_general.py` — reconciliación multi-página, secciones HEMATOLOGIA/HEMOSTASIA/QUÍMICA/IONOGRAMA
- [ ] 4.3 Test + impl `parsing/ecg_mortara.py` — tolerancia a `PID / NAME MISMATCH`
- [ ] 4.4 Test + impl `parsing/echo_doppler.py` — medidas + texto libre por sección + firma

## Fase 5: Detección de PII

- [ ] 5.1 Test + impl `src/anonimizacion/pii/recognizers/dni_ar.py` (regex + validación formato)
- [ ] 5.2 Test + impl `pii/engine.py` (Presidio + spaCy es_core_news_lg, IDs internos como cuasi-identificadores, baja confianza marcada)
- [ ] 5.3 Test + impl `pii/policy.py` — namespace propio para médico (`physician_id`), texto libre incluido

## Fase 6: Pseudonimización y Linkage

- [ ] 6.1 Test + impl `pseudonym/salt_store.py` (pepper desde env/archivo cifrado, nunca en repo)
- [ ] 6.2 Test + impl `pseudonym/keys.py` — HMAC `patient_id` (canonicalización DNI) y `patient_alt_id`
- [ ] 6.3 Test + impl `pseudonym/key_resolver.py` — lab como puente alt_id→patient_id, `PII_UNRESOLVED_KEY`
- [ ] 6.4 Test + impl `pseudonym/linkage.py` — clustering por ancla ±7 días, `episode_id`, casos borde (7 vs 8 días, empates)

## Fase 7: Emit / Storage

- [ ] 7.1 Modelo SQLAlchemy + migración: `patient_link`, `episode`, `ecg_measurement`, `lab_result` (EAV), `echo_measurement`, `echo_section_text`
- [ ] 7.2 Test + impl `emit/record_builder.py` (ParsedDocument+PatientKeys → AnonymizedRecord)
- [ ] 7.3 Test + impl `emit/sinks/postgres.py`
- [ ] 7.4 Test + impl `emit/sinks/parquet.py` (particionado doc_type/año)
- [ ] 7.5 Test + impl `emit/quarantine.py` — solo doc_id+código+etapa

## Fase 8: Pipeline / Runner

- [ ] 8.1 Test + impl `pipeline/stages.py`, `pipeline/result.py`
- [ ] 8.2 Test + impl `pipeline/runner.py` — aislamiento de fallo por documento, reintentos solo en errores transitorios

## Fase 9: Workers

- [ ] 9.1 Impl `workers/app.py` (Celery), `workers/retry_policy.py` (backoff 5s/30s/180s)
- [ ] 9.2 Test + impl `workers/tasks.py` — mensaje de cola solo `{doc_id, uri, sha256}`

## Fase 10: Observability

- [ ] 10.1 Test + impl `observability/safe_logging.py` — whitelist de campos + filtro de redacción (property test: PII nunca en salida)
- [ ] 10.2 Impl `observability/metrics.py`

## Fase 11: Integración / E2E

- [ ] 11.1 Fixtures sintéticas versionadas por tipo en `tests/fixtures/`
- [ ] 11.2 Test integración: 1 documento roto en lote de N no aborta el lote, queda en cuarentena
- [ ] 11.3 Test integración: escaneo del output con `pii.engine` no encuentra PII
- [ ] 11.4 Test E2E: ECG+Lab+Eco sintéticos del mismo paciente ≤7 días → mismo `patient_id`/`episode_id`
- [ ] 11.5 Test seguridad: socket bloqueado en la suite, ninguna llamada de red
