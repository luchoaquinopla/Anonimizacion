# Tareas: Ingesta de PDFs clínicos anonimizada

## Review Workload Forecast

| Field | Value |
| ------- | ------- |
| Estimated changed lines | 650–1.000 (spike, contratos, pruebas y expansión planificada) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: spike local de laboratorio sin persistencia → PR 2: evaluación habilitable con corpus aprobado → PR 3: persistencia y familias adicionales |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

## Límites del incremento inicial

El primer incremento implementable es exclusivamente un *spike* local, en memoria, para PDFs digitales de laboratorio: no crea persistencia, migraciones, broker, fuente remota, corpus/fixtures ni seudonimización. Las expansiones quedan bloqueadas explícitamente hasta contar con decisiones y evidencia aprobadas.

## Fase 1. Decisiones bloqueantes de negocio, clínica y privacidad

### 1.1. Aprobaciones requeridas antes de habilitar datos

- Acordar con clínica y privacidad el inventario versionado de campos de laboratorio, cuáles son requeridos u opcionales, las reglas para `not_present` y la política que habilita o rechaza un documento; registrar la decisión en `openspec/changes/ingesta-pdf-clinicos/` antes de implementar cualquier persistencia.
- Proveer y autorizar un corpus de laboratorio anotado, junto con los umbrales numéricos de cobertura, exactitud de valor/unidad, omisiones, rechazo y PII residual; no inferirlos desde las muestras conocidas.
- Definir la fuente autorizada del flujo PDF, la expiración de acceso, el identificador técnico no identificante y el procedimiento de reingesta; no seleccionar broker ni contrato de cola hasta conocer volumen y operación.
- Resolver con producto y privacidad si habrá vinculación longitudinal/señal ECG; exigir aprobación de seudonimización para lo primero y una fuente nativa validada (no trazado PDF) para lo segundo.

## Fase 2. PR 1 — Spike local de laboratorio, efímero y sin persistencia

### 2.1. Contrato y límites del núcleo

- [ ] RED: crear pruebas unitarias en `tests/unit/` que fijen los estados exhaustivos (`verified`, `not_present`, `missing`, `ambiguous`, `malformed`, `truncated`), la resolución de todo campo del inventario y el rechazo por PII, campos requeridos no verificables o controles incompletos. <!-- sdd-owner: implementation -->
- [ ] GREEN: crear los tipos puros y la política de decisión en `src/clinical_ingestion/domain/` para un `ExtractionResult` efímero y un `ApprovedDocument` sin PDF, texto fuente, PII/PHI, identificadores ni fechas reidentificantes; hacer que la política produzca sólo aprobación o códigos/métricas técnicas no identificantes de rechazo. <!-- sdd-owner: implementation -->
- [ ] TRIANGULATE: añadir casos unitarios de valores malformados/truncados, unidades incompatibles, candidatos múltiples y ausencia legítima opcional en `tests/unit/`, verificando que ningún campo se omite silenciosamente. <!-- sdd-owner: implementation -->
- [ ] REFACTOR: simplificar nombres y separar reglas de dominio de detalles PDF en `src/clinical_ingestion/domain/`; ejecutar el comprobador de pruebas que se incorpore con el spike y documentar el comando real en la verificación posterior, sin asumir un runner existente. <!-- sdd-owner: implementation -->

### 2.2. Adaptador local de laboratorio

- [ ] RED: añadir pruebas de adaptador en `tests/unit/` con entradas de texto/bloques en memoria representativas y no identificantes para clasificación de laboratorio, procedencia técnica (página/bloque) y conversión al contrato; no añadir PDFs reales ni fixtures clínicos al repositorio. <!-- sdd-owner: implementation -->
- [ ] GREEN: implementar en `src/clinical_ingestion/adapters/outbound/` un extractor local en memoria basado en PyMuPDF y en `src/clinical_ingestion/application/` el puerto `FamilyAdapter` para laboratorio, inyectando los bytes/flujo y descartándolos al terminar; no escribir temporales, logs de contenido ni implementar almacenamiento. <!-- sdd-owner: implementation -->
- [ ] TRIANGULATE: ampliar `tests/unit/` para orden de lectura variable, filas de tabla incompletas y dos candidatos, comprobando estados y procedencia sin conservar texto extraído. <!-- sdd-owner: implementation -->
- [ ] REFACTOR: aislar el mapeo de laboratorio detrás del adaptador y revisar `src/clinical_ingestion/` para que dominio y aplicación no dependan de PyMuPDF; dejar explícito en el código/configuración que `pdfplumber` y OCR no forman parte del spike. <!-- sdd-owner: implementation -->

### 2.3. Privacidad y demostración local acotada

- [ ] Implementar en `src/clinical_ingestion/application/` los puertos `DocumentSource` y `PrivacyValidator` con sustitutos locales en memoria, más un validador residual independiente; verificar en `tests/unit/` que un hallazgo bloquea el resultado y sólo devuelve códigos/conteos permitidos. <!-- sdd-owner: implementation -->
- [ ] Crear una entrada local mínima en `src/clinical_ingestion/bootstrap/` (CLI o composición invocable, según se detecte al iniciar el código) que procese un flujo de laboratorio en memoria y muestre únicamente estado, versión, tipo y métricas agregadas; verificar manualmente que no crea archivos ni requiere red, base de datos o broker. <!-- sdd-owner: implementation -->
- [ ] Documentar en `openspec/changes/ingesta-pdf-clinicos/` la evidencia del spike (comandos reales, resultado, limitaciones y ausencia de persistencia) sin incluir contenido clínico ni copiar una muestra PDF. <!-- sdd-owner: implementation -->

## Fase 3. PR 2 — Expansión deliberadamente bloqueada por corpus y umbrales aprobados

### 3.1. Evaluación de calidad habilitable

- [ ] Tras recibir el corpus autorizado, inventario y umbrales aprobados de la fase 1, implementar en `src/clinical_ingestion/` y `tests/` el evaluador por familia/campo/versión que informe cobertura, exactitud de valor/unidad, omisiones, rechazos y PII residual, sin almacenar corpus ni contenido fuente. <!-- sdd-owner: implementation -->
- [ ] Tras aprobar la política de aptitud, conectar el evaluador a la decisión de habilitación para bloquear versiones sin umbral o bajo umbral y registrar sólo métricas técnicas permitidas; verificarlo contra el corpus autorizado fuera del repositorio. <!-- sdd-owner: implementation -->

## Fase 4. PR 3 — Persistencia y familias adicionales, sólo con aprobaciones previas

### 4.1. Persistencia aprobada y trazable

- [ ] Después de definir fuente, retención y esquema con privacidad, implementar `ApprovedObservationStore`, migraciones y pruebas de integración en las rutas concretas acordadas para persistir exclusivamente campos `verified` de documentos aprobados; demostrar que rechazos, PDF y texto crudo no se persisten. <!-- sdd-owner: implementation -->
- [ ] Después de aprobar inventarios y corpus por familia, incorporar adaptadores versionados de ecocardiografía y ECG de metadatos/medidas textuales con sus pruebas de regresión; excluir expresamente señal del trazado ECG y cualquier vínculo longitudinal no aprobado. <!-- sdd-owner: implementation -->
- [ ] Tras aprobar definiciones de features, implementar en `src/clinical_ingestion/` la derivación versionada desde observaciones aprobadas y pruebas que excluyan estados distintos de `verified`; no introducir target de predicción. <!-- sdd-owner: implementation -->

## Acciones de revisión y puertas de ciclo de vida

- [ ] Iniciar o reutilizar una revisión acotada del PR 1, comprobando el límite de no persistencia, la ausencia de contenido sensible en pruebas/logs y que el diff permanezca dentro del presupuesto antes de aplicar. <!-- sdd-owner: parent -->
- [ ] Antes de iniciar PR 2 o PR 3, resolver la decisión de entrega por riesgo alto (cadena o excepción) y confirmar que las aprobaciones de la fase correspondiente están documentadas. <!-- sdd-owner: parent -->
