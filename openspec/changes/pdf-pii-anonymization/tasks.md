# Tareas: Pipeline de extracción y anonimización de PDFs clínicos

## Review Workload Forecast

| Campo | Valor |
|---|---|
| Líneas estimadas | 3500-5000+ (9 fases, ~15 módulos nuevos, esquema SQL, Celery, motor PII) |
| Riesgo de presupuesto 400 líneas | High |
| PRs encadenados recomendados | Yes |
| Split sugerido | PR1→PR9 (ver Work Units) |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: No (resuelto — stacked-to-main)
Chained PRs recommended: Yes
400-line budget risk: High

### Suggested Work Units

| Unit | Objetivo | PR | Notas |
|---|---|---|---|
| 1 | Fase 0+1: runner de tests + dominio | PR1 | Base de todo; sin dependencias |
| 2 | Fase 2+3: ingesta, extracción PyMuPDF, detección de tipo | PR2 | Depende de PR1 |
| 3 | Fase 4: parseo (Protocol+registro+3 parsers) | PR3 | Depende de PR2; parsers independientes entre sí |
| 4 | Fase 5: detección de PII | PR4 | Depende de PR1 (dominio); paralelo a PR3 |
| 5 | Fase 6: pseudonimización + vinculación ±7d | PR5 | Depende de PR4 |
| 6 | Fase 7: salida/storage (Postgres+Parquet+cuarentena) | PR6 | Depende de PR3+PR5; incluye migraciones SQL |
| 7 | Fase 8+9: pipeline ejecutor + trabajadores Celery | PR7 | Depende de PR6 |
| 8 | Fase 10: observabilidad | PR8 | Depende de PR1; puede ir en paralelo temprano |
| 9 | Fase 11: integración/E2E con fixtures sintéticas | PR9 | Depende de todo lo anterior |

## Convención de nombres

Archivos, módulos, clases, funciones y variables en **español** (ver `AGENTS.md`). Se mantienen sin
traducir los términos técnicos de facto (`pipeline`, `pii`, `pepper`, `hash`) y los nombres impuestos por
librerías de terceros o convenciones de framework (`conftest.py`, `app.py` de Celery, `SecretStr` de
Pydantic).

## Fase 0: Infraestructura de Tests

- [x] 0.1 Elegir pytest como test runner; agregar a `pyproject.toml` (`pytest`, `pytest-cov`)
- [x] 0.2 Configurar `openspec/config.yaml`: `apply.tdd: true`, `apply.test_command: "pytest"`, `verify.test_command: "pytest"`
- [x] 0.3 Crear `tests/` con `conftest.py` y estructura `tests/fixtures/` (sintéticas)

## Fase 1: Dominio (Foundation)

- [x] 1.1 Crear `pyproject.toml` con stack base (pydantic, pytest, pytest-cov) — pymupdf/presidio/spacy/celery/redis/sqlalchemy/pyarrow se agregan en PR2+ según Work Units
- [x] 1.2 Test + impl `src/anonimizacion/dominio/tipos_documento.py` (`TipoDocumento` enum)
- [x] 1.3 Test + impl `src/anonimizacion/dominio/errores.py` (`ErrorDocumento`, `ErrorParseo` tipados)
- [x] 1.4 Test + impl `src/anonimizacion/dominio/modelos.py`: `DocumentoParseado`, `IdentidadCruda` (SecretStr, `__repr__` redactado), `ClavesPaciente`, `RegistroAnonimizado`

## Fase 2: Ingesta + Extracción

- [x] 2.1 Test + impl `src/anonimizacion/ingesta/artefacto.py` (`ArtefactoCrudo`: uri+sha256+formato)
- [x] 2.2 Test + impl `src/anonimizacion/ingesta/fuente.py` (`FuenteArtefacto` filesystem)
- [x] 2.3 Test + impl `src/anonimizacion/extraccion/texto_pymupdf.py` — spec pdf-text-extraction: texto nativo sin OCR, fallo explícito en PDF corrupto (fixtures lab/ECG sintéticas)

## Fase 3: Detección de Tipo de Documento

- [x] 3.1 Test + impl `src/anonimizacion/deteccion/firmas/` (marcadores por tipo) y `detector_tipo.py` — spec document-type-detection: clasificación + `TIPO_NO_RECONOCIDO` sin abortar

## Fase 4: Parseo

- [x] 4.1 Test + impl `src/anonimizacion/parseo/base.py` (`ParseadorDocumento` Protocol) + `registro.py`
- [x] 4.2 Test + impl `parseo/laboratorio_general.py` — reconciliación multi-página, secciones HEMATOLOGIA/HEMOSTASIA/QUÍMICA/IONOGRAMA
- [x] 4.3 Test + impl `parseo/ecg_mortara.py` — tolerancia a `PID / NAME MISMATCH`
- [x] 4.4 Test + impl `parseo/eco_doppler.py` — medidas + texto libre por sección + firma

## Fase 5: Detección de PII

- [x] 5.1 Test + impl `src/anonimizacion/pii/reconocedores/dni_ar.py` (regex + validación formato)
- [x] 5.2 Test + impl `pii/motor.py` (Presidio + spaCy es_core_news_lg, IDs internos como cuasi-identificadores, baja confianza marcada)
- [x] 5.3 Test + impl `pii/politica.py` — namespace propio para médico (`id_medico`), texto libre incluido

## Fase 6: Pseudonimización y Vinculación

- [x] 6.1 Test + impl `pseudonimizacion/almacen_pepper.py` (pepper desde env/archivo cifrado, nunca en repo)
- [x] 6.2 Test + impl `pseudonimizacion/claves.py` — HMAC `id_paciente` (canonicalización DNI) y `id_alt_paciente`
- [x] 6.3 Test + impl `pseudonimizacion/resolutor_claves.py` — lab como puente id_alt_paciente→id_paciente, `CLAVE_PII_NO_RESUELTA`
- [x] 6.4 Test + impl `pseudonimizacion/vinculacion.py` — clustering por ancla ±7 días, `id_episodio`, casos borde (7 vs 8 días, empates)

## Fase 7: Salida / Storage

- [ ] 7.1 Modelo SQLAlchemy + migración: `vinculo_paciente`, `episodio`, `medicion_ecg`, `resultado_laboratorio` (EAV), `medicion_eco`, `texto_seccion_eco`
- [ ] 7.2 Test + impl `salida/constructor_registro.py` (DocumentoParseado+ClavesPaciente → RegistroAnonimizado)
- [ ] 7.3 Test + impl `salida/destinos/postgres.py`
- [ ] 7.4 Test + impl `salida/destinos/parquet.py` (particionado tipo_documento/año)
- [ ] 7.5 Test + impl `salida/cuarentena.py` — solo id_documento+código+etapa

## Fase 8: Pipeline / Ejecutor

- [ ] 8.1 Test + impl `pipeline/etapas.py`, `pipeline/resultado.py`
- [ ] 8.2 Test + impl `pipeline/ejecutor.py` — aislamiento de fallo por documento, reintentos solo en errores transitorios

## Fase 9: Trabajadores

- [ ] 9.1 Impl `trabajadores/app.py` (Celery), `trabajadores/politica_reintentos.py` (backoff 5s/30s/180s)
- [ ] 9.2 Test + impl `trabajadores/tareas.py` — mensaje de cola solo `{id_documento, uri, sha256}`

## Fase 10: Observabilidad

- [ ] 10.1 Test + impl `observabilidad/bitacora_segura.py` — whitelist de campos + filtro de redacción (property test: PII nunca en salida)
- [ ] 10.2 Impl `observabilidad/metricas.py`

## Fase 11: Integración / E2E

- [ ] 11.1 Fixtures sintéticas versionadas por tipo en `tests/fixtures/`
- [ ] 11.2 Test integración: 1 documento roto en lote de N no aborta el lote, queda en cuarentena
- [ ] 11.3 Test integración: escaneo del output con `pii.motor` no encuentra PII
- [ ] 11.4 Test E2E: ECG+Lab+Eco sintéticos del mismo paciente ≤7 días → mismo `id_paciente`/`id_episodio`
- [ ] 11.5 Test seguridad: socket bloqueado en la suite, ninguna llamada de red
