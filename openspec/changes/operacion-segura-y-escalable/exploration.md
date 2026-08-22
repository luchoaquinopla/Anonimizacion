## Exploration: operacion-segura-y-escalable

### Current State
El pipeline ya usa PyMuPDF, Strategies por ECG/laboratorio/eco, reconciliación antes de PII/pseudonimización/salida, HMAC, Postgres y Parquet. `scripts/procesar_carpeta.py` es manual y exige Python, dependencias, Postgres y pepper; crea el esquema directamente y no exporta Parquet. `docker-compose.yml` sólo levanta Postgres/pgAdmin.

`EjecutorPipeline.procesar_lote` vincula episodios correctamente sobre un lote completo. En contraste, `trabajadores/tareas.py::procesar_documento` llama `procesar_lote([item])`: una tarea por PDF no puede ensamblar un episodio multiestudio. No hay worker/Redis/composición de producción. Parquet está por tipo/año; no hay bundle por paciente/episodio.

El eco no presenta regresión reproducible: 40 pruebas focalizadas parser/reconciliación/E2E pasan. No existe PDF real ni registro seguro de cuarentena del fallo reportado; no puede afirmarse causa. El parser fue calibrado contra una muestra real y sus heurísticas de header, tabla, secciones y firma pueden no cubrir una variante de layout.

### Affected Areas
- `scripts/procesar_carpeta.py` — reemplazar operación manual por composición instalable.
- `src/anonimizacion/pipeline/ejecutor.py` — separar trabajo por PDF de coordinación/commit de episodio.
- `src/anonimizacion/trabajadores/{app,tareas}.py` — eliminar la semántica incorrecta de tarea individual por PDF.
- `src/anonimizacion/{ingesta,salida}/` — corrida durable, manifiesto, storage de originales y bundles seguros.
- `src/anonimizacion/salida/destinos/{postgres,parquet}.py` — Postgres como fuente de verdad; proyecciones de bundles y analítica.
- `src/anonimizacion/{parseo,reconciliacion}/eco_doppler.py` — corrección dirigida por caso reproducible.
- `tests/fixtures/`, `tests/integracion/` — generación sintética masiva con oráculo.
- `docs/pipeline.md` y notas Obsidian — actualizar arquitectura sólo al aprobar/implementar; bitácora por hito.

### Approaches
1. **Instalador Windows + servicio local** — paquete firmado (PyInstaller) y servicio Windows con cuenta restringida; configura directorios, secretos y DB institucional/local.
   - Pros: el médico no instala Docker ni opera comandos; offline; ACLs y pepper aislados.
   - Cons: empaquetar Presidio/spaCy y administrar actualizaciones/DB aumenta complejidad.
   - Effort: High.

2. **Aplicación instalable con batch síncrono inicial y servicio opcional** — CLI/UI mínima para entrada/salida, migraciones y configuración; procesa corridas completas con paralelismo acotado y Postgres institucional.
   - Pros: preserva episodio, no exige Docker/Redis, menor superficie operativa y camino seguro a producción.
   - Cons: menos paralelismo/monitorización que cola distribuida; necesita reanudación durable.
   - Effort: Medium.

3. **Contenedores/Kubernetes** — API, workers Celery/Redis y object storage.
   - Pros: escalado horizontal y observabilidad.
   - Cons: contradice la restricción operativa y es prematuro.
   - Effort: High.

4. **Bundles por episodio + Parquet derivado** — escribir `dataset_anonimizado/<id_paciente>/<id_episodio>/manifest.json` y archivos extraídos por estudio; originales cifrados y cuarentena fuera del dataset; Parquet para entrenamiento.
   - Pros: satisface carpetas sin PII ni acoplar modelos a paths; reexportable/idempotente.
   - Cons: requiere transacciones, versionado y duplicación controlada de derivados.
   - Effort: Medium.

5. **Dataset público como validador de parser** — usar corpus externo en lugar de fixtures institucionales.
   - Pros: menor costo si existiera.
   - Cons: no hay evidencia de corpus público masivo con los layouts PDF, español y reglas del instituto; no es viable como validación primaria.
   - Effort: Not viable as primary validation.

### Recommendation
Adoptar enfoque 2: aplicación Windows instalable, offline, con operación carpeta entrada/salida y Postgres + servicio de secretos. La unidad debe ser una **corrida durable**: inventariar PDFs, extraer tipo/fecha/clave mínima, resolver `id_paciente`, acumular candidatos y coordinar/persistir episodios. Paralelizar sólo etapas por PDF; ensamblar episodio después. No usar la tarea Celery actual por PDF.

Postgres permanece fuente de verdad. Cada episodio aprobado emite proyecciones idempotentes: (a) bundle `patient_id/episode_id` con manifest y datos seguros por estudio; (b) Parquet analítico derivado. Nunca PDF crudo en dataset.

Para escala sin datos reales: generador parametrizable de PDFs sintéticos con oráculo para miles de episodios, ventanas por tipo, duplicados, homónimos, faltantes, ambigüedad, PDFs corruptos y variaciones de layout. Synthea sirve como insumo de identidades/historias sintéticas, pero se deben renderizar PDFs desde templates propias. PTB-XL (21.799 ECG 12 derivaciones) y MIMIC-IV-ECG (~800.000 ECG de ~160.000 pacientes) sirven para ML/datos y no validan parsers/anonimización de PDFs. Presidio es reusable, pero no garantiza cobertura completa de PII: se conserva reconciliación y reglas custom.

Antes de modificar eco, agregar métricas seguras de cuarentena por tipo/código/campo/página y correr el caso real en servidor. Crear fixture sintética mínima desde su layout y corregir con TDD. No relajar reconciliación para hacerlo pasar.

Al aprobar decisiones/implementaciones, actualizar la nota de Arquitectura de Obsidian y registrar hito separado. Las fuentes aceptadas van a bibliografía relevante como nota con enlace, fecha, finalidad y limitación.

Fuentes primarias:
- Presidio: https://microsoft.github.io/presidio/
- Synthea: https://synthetichealth.github.io/synthea/
- PTB-XL: https://physionet.org/content/ptb-xl/1.0.3/
- MIMIC-IV-ECG: https://physionet.org/content/mimic-iv-ecg/1.0/

### Risks
- Sin Docker no desaparecen secretos, actualizaciones, DB, permisos ni recuperación.
- Paralelizar por PDF sin coordinador durable rompe la semántica de episodio.
- Carpetas con nombre/DNI o PDFs originales reintroducen PII.
- El eco requiere código/campo/página de cuarentena o PDF de referencia anonimizado para corrección comprobable.
- Cinecoronariografía no tiene muestra ni parser; no debe fingirse soporte.
- Datasets públicos pueden tener restricciones de acceso/licencia y no reemplazan fixtures institucionales.

### Ready for Proposal
Yes — proponer work units: (1) telemetría segura y diagnóstico eco; (2) corrida/ensamblador de episodios y bundle storage; (3) empaquetado y operación Windows; (4) generación sintética/carga. No prometer arreglo de eco sin evidencia reproducible.
