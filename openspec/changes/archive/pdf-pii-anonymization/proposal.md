# Proposal: Pipeline de extracción y anonimización de PDFs clínicos

## Intent

El proyecto de investigación del Instituto de Cardiología de Corrientes necesita ~100.000 registros
de ECG + laboratorio + ecocardiograma para entrenar un modelo de DL. Hoy esos datos solo existen
como PDFs con PII de pacientes (nombre, DNI, fecha de nacimiento), imposibles de usar como dataset
sin violar la Ley 25.326 y el acuerdo de confidencialidad del protocolo. Este cambio construye el
pipeline que convierte esos PDFs en datos estructurados anonimizados, **vinculables entre sí por
paciente** sin persistir jamás el DNI real.

## Scope

### In Scope
- Extracción de texto nativo (PyMuPDF) de los 3 layouts: ECG Mortara, laboratorio, ecocardiograma.
- Detección de tipo de documento + un parser por tipo (patrón Strategy), sin `if/elif` monolítico.
- Detección de PII 100% offline: Presidio + spaCy `es_core_news_lg` + recognizer custom de DNI.
- Generación de `patient_id` pseudónimo estable (HMAC de DNI + salt guardado aparte) **antes** de
  descartar la PII, para permitir el cruce de documentos con ventana de ±7 días.
- Salida estructurada anonimizada por tipo de documento (medidas de ECG, tabla de pruebas de
  laboratorio, medidas y texto de eco).
- Arquitectura de procesamiento async (cola + worker pool) desde el día 1, con reintentos.

### Out of Scope
- El modelo de deep learning consumidor (proyecto separado).
- PDF visualmente redactado (el consumidor es un modelo, no un humano).
- OCR (los 3 tipos son texto nativo); queda como fallback futuro.
- Extracción de señal cruda de ECG en formato nativo del equipo (ver Riesgo R1).
- Cualquier servicio cloud de OCR/NER.

## Capabilities

### New Capabilities
- `pdf-text-extraction`: extracción de texto y posición desde PDF de texto nativo.
- `document-type-detection`: clasificación del layout y despacho al parser correspondiente.
- `document-parsing`: parsers por tipo que producen un modelo de documento tipado.
- `pii-detection`: identificación de nombre, DNI, fecha de nacimiento e IDs internos.
- `pseudonymous-linkage`: `patient_id` estable + regla de cruce por ventana de ±7 días.
- `anonymized-output`: emisión del registro estructurado sin PII.
- `batch-processing`: cola async, workers, reintentos y trazabilidad sin loguear PII.

### Modified Capabilities
- None (repositorio greenfield, `openspec/specs/` vacío).

## Approach

Pipeline en etapas desacopladas: `ingest → detect-type → parse → detect-PII → pseudonymize →
emit`. Cada etapa es reemplazable; agregar un 4to layout implica agregar un parser, no tocar el
core. Python por ser el único ecosistema maduro de NER en español self-hosted. La pseudonimización
ocurre **dentro** del pipeline, antes de cualquier escritura de salida: la PII cruda nunca sale del
proceso ni entra en logs.

## Affected Areas

| Área | Impacto | Descripción |
|---|---|---|
| `src/` | Nuevo | Todo el pipeline (extractores, parsers, detección de PII, pseudonimización) |
| `tests/` | Nuevo | Fixtures sintéticas por tipo de documento — nunca PDFs reales |
| `pyproject.toml` | Nuevo | Stack Python: PyMuPDF, Presidio, spaCy |
| `openspec/config.yaml` | Modificado | Activar `tdd: true` y `test_command` una vez definido el runner |

## Risks

| Riesgo | Prob. | Mitigación |
|---|---|---|
| R1: el ECG solo trae el trazado como imagen rasterizada; si el DL necesita la señal cruda, el PDF no alcanza | Alta | Decisión de negocio fuera de este repo. El pipeline se diseña para admitir una fuente paralela (XML/SCP-ECG) sin rediseño |
| R2: falso negativo en detección de PII = fuga real de DNI | Media | Enfoque híbrido NER+regex, umbral conservador, suite de tests con fixtures sintéticas antes de correr a escala |
| R3: fuga del salt del `patient_id` permite re-identificar todo el dataset | Baja | Salt en almacén separado con acceso restringido, nunca en el repo ni junto al dataset |
| R4: PII filtrada en logs/stack traces | Media | Política explícita: solo metadata (id de documento, tipo, resultado) |
| R5: variaciones de layout no previstas rompen el parser | Media | Detector desacoplado + fallo explícito por documento sin abortar el lote |

## Rollback Plan

Repositorio greenfield: no hay sistema en producción que revertir. El rollback es descartar la rama
del cambio. Operativamente, si el pipeline produce salida defectuosa, se descarta el dataset
generado y se reprocesa desde los PDFs originales, que siguen siendo la fuente de verdad.

## Dependencies

- Modelo spaCy `es_core_news_lg` descargable y cacheado localmente (sin acceso a internet en runtime).
- Definición del stack de cola/worker y del almacén del salt.
- Acceso al corpus real de PDFs para validación (fuera del repositorio).

## Open Questions (a resolver en sdd-design / por el usuario)

1. **Storage de la salida estructurada**: SQL, NoSQL o híbrido. Impacta el modelo de datos y la
   estrategia de cruce por ±7 días.
2. **Retención y cifrado de los PDFs originales en reposo**: ¿se borran tras procesar o se retienen?
   ¿con qué política de cifrado?
3. **Política sobre el nombre del médico derivante/informante**: ¿PII a anonimizar igual que la del
   paciente, o dato profesional retenible?
4. **Señal cruda de ECG (R1)**: ¿el modelo de DL requiere la serie temporal o alcanzan las medidas
   numéricas (PR, QRS, QT/QTc) extraíbles como texto?

## Success Criteria

- [ ] Los 3 tipos de documento se procesan produciendo salida estructurada tipada.
- [ ] Ningún registro de salida contiene nombre, DNI ni fecha de nacimiento reales.
- [ ] Dos documentos del mismo paciente con fechas dentro de ±7 días quedan vinculados por el mismo
      `patient_id`, sin que el DNI real exista en el dataset.
- [ ] Agregar un 4to tipo de documento no requiere modificar el core del pipeline.
- [ ] Ninguna llamada de red a servicios externos durante el procesamiento.
- [ ] Ningún log contiene PII cruda.
