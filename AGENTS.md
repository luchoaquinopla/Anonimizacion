# AGENTS.md — anonimizacion

Guía para cualquier agente (humano o IA) que trabaje en este repositorio.

## Qué es este proyecto

Pipeline de **extracción y anonimización** de datos clínicos contenidos en PDFs, para el
proyecto de investigación del Instituto de Cardiología de Corrientes: *"Identificación de
Patrones electrocardiográficos relacionados a laboratorio de análisis clínicos y
ecocardiograma Doppler usando IA"*.

**Scope de este repo**: extraer datos estructurados de 3 tipos de documento PDF y
anonimizarlos. **NO incluye** el modelo de deep learning que consumirá esos datos — eso es
un proyecto consumidor separado, fuera de este alcance.

Volumen: hoy 3 documentos de muestra, objetivo ~100.000 registros (retrospectivo,
observacional).

## Los 3 tipos de documento

Todos son PDF de **texto nativo** (no escaneados) generados por sistemas del instituto.
Fixtures reales de muestra (ver `docs/samples/` una vez anonimizadas — nunca commitear las
originales con PII real, ver sección Seguridad).

### 1. ECG (equipo Mortara)
- Header: nombre completo, ID interno de estudio, fecha/hora, institución, edad, sexo,
  técnico, médico derivante.
- Medidas: Vent. rate, PR interval, QRS duration, QT/QTc, P-R-T axes.
- **Riesgo técnico abierto**: el trazado se exporta como **imagen rasterizada**, no como
  señal digital (serie temporal). Si el modelo de DL necesita la señal cruda para detectar
  patrones, un PDF con imagen no alcanza — evaluar extraer el formato nativo del equipo
  (XML/SCP-ECG) en paralelo al PDF. Pendiente de decisión de negocio.
- El equipo puede emitir advertencias propias (ej. `PID / NAME MISMATCH`) — el parser debe
  tolerarlas sin romper.

### 2. Laboratorio de análisis clínicos
- Header (repetido en cada página, documento multi-página): Apellido y Nombre, DNI,
  Fecha de Nacimiento, Edad, Médico derivante, Nº de Petición, Fecha, Hora de Extracción,
  Origen.
- Cuerpo: tabla de pruebas organizada en secciones (HEMATOLOGIA, HEMOSTASIA, QUÍMICA
  CLÍNICA, IONOGRAMA, etc.), cada fila con Resultado Actual, Unidades, Valores de
  Referencia. Esta es la parte más rica en features estructuradas.

### 3. Ecocardiograma Doppler
- Header: Paciente, Documento (DNI), Nº de Estudio, Fecha, Médico Solicitante, Peso,
  Altura, Superficie Corporal.
- Cuerpo: tabla de medidas (AO, AI, DDVI, DSVI, FA, Septum, P. Posterior, etc.) + texto
  libre por sección (motilidad segmentaria, válvulas, pericardio, flujos Doppler,
  conclusiones) + firma del médico informante (nombre + matrícula).

## Requisito de vinculación entre documentos (clave de diseño)

Los 3 documentos de un mismo paciente deben cruzarse cuando la diferencia entre sus fechas
es de **hasta 7 días**. Esto significa que la anonimización **no puede ser un simple
borrado** del DNI: se necesita un `patient_id` pseudónimo estable (ej. HMAC del DNI + salt
guardado aparte del dataset) generado antes de descartar los datos identificatorios reales,
para poder unir ECG + Laboratorio + Ecocardiograma del mismo paciente en el dataset final.

## Datos personales a tratar (PII)

- Nombre y apellido del paciente
- DNI
- Fecha de nacimiento (cuasi-identificador combinado con DNI/edad)
- Nº de Petición / Nº de Estudio / IDs internos del equipo (potencialmente
  re-identificantes si permiten buscar en el sistema del instituto — tratar igual que PII)
- Nombre del médico derivante/informante: es PII de un profesional, no del paciente —
  política de conservación a confirmar en `sdd-propose` (probablemente no requiere el
  mismo nivel de anonimización que los datos del paciente).

## Decisiones de arquitectura ya tomadas

| Decisión | Elegido | Por qué |
|---|---|---|
| Procesamiento cloud vs self-hosted | **100% self-hosted / offline** | DNI es dato sensible (Ley 25.326); el protocolo de investigación exige confidencialidad, no se puede enviar a APIs de terceros |
| Formato de salida | **Datos estructurados** (no PDF redactado) | El consumidor final es un modelo de DL, no una persona leyendo el PDF |
| Lenguaje | **Python** | Único ecosistema maduro para NER en español self-hosted (Presidio + spaCy `es_core_news_lg`) |
| Extracción PDF | **PyMuPDF** nativo, OCR (Tesseract) solo como fallback | Los 3 tipos son texto nativo, no escaneados |
| Detección de PII | **Presidio + spaCy + reconocedor custom de DNI** | Regex solo tiene falsos negativos inaceptables para anonimización; NER solo no valida el formato de DNI |
| Arquitectura de escala | Cola async (worker pool) + patrón Strategy/Plugin por tipo de documento | Escalar de 3 a ~100k sin que agregar un 4to layout rompa mantenibilidad |

Pendiente de definir en `sdd-propose`: storage final (SQL vs NoSQL vs ambos), política sobre
nombre del médico, y la decisión sobre señal cruda de ECG (ver riesgo técnico arriba).

## Seguridad y manejo de datos (no negociable)

- **Nunca** commitear PDFs reales de pacientes ni datos de muestra con PII real al
  repositorio. Fixtures de test deben ser sintéticas o estar anonimizadas antes de
  entrar al repo.
- **Nunca** loguear PII cruda (nombre, DNI, fecha de nacimiento) en logs de aplicación,
  stack traces, ni herramientas de monitoreo.
- Los PDFs originales en disco/storage deben estar cifrados en reposo, con retención
  corta definida (a fijar en `sdd-propose`).
- El salt/clave usada para generar `patient_id` pseudónimos se guarda separado del
  dataset de features, con acceso restringido.

## Convenciones de código

- Nombres de archivos, funciones, variables y constantes: **español**. Esto incluye
  identificadores de dominio (`fecha_nacimiento`, no `date_of_birth`), nombres de módulos y
  de tests. Palabras reservadas del lenguaje/librerías (`class`, `def`, `return`, nombres de
  API de terceros como `SecretStr` o `Protocol`) se mantienen como las define la librería.
- Comentarios: **cortos y concisos** — una línea siempre que se pueda. Solo explicar el
  *por qué* cuando no sea obvio (una decisión no evidente, una restricción externa); nunca
  repetir en prosa lo que el código ya dice. Nada de bloques de comentario largos ni
  docstrings de varios párrafos.
- Mensajes de error y logs: español, mismas reglas de brevedad.
- Documentación del proyecto (este archivo, `openspec/`, README): **español**, porque el
  dominio y los documentos fuente son en español.
- Un parser/extractor por tipo de documento, implementando una interfaz común (patrón
  Strategy) — no un parser monolítico con `if/elif` por tipo.
- Todo test que use un PDF de muestra debe usar fixtures sintéticas, nunca los PDFs reales
  que se compartan en la conversación de diseño.

## Estado del proyecto (SDD)

Persistencia: `hybrid` (OpenSpec + Engram). Ver `openspec/` para specs formales y
[`docs/pipeline.md`](docs/pipeline.md) para el diagrama de flujo y la explicación de por qué se
eligió cada librería del stack (PyMuPDF, Presidio+spaCy, HMAC, Celery+Redis, Postgres+Parquet).

- ✅ `sdd-init` corrido (proyecto `anonimizacion`)
- ✅ `sdd-explore` corrido — comparación de enfoques para extracción, detección de PII,
  arquitectura de escala (ver Engram `sdd/pdf-pii-anonymization/explore`)
- ✅ Análisis de PDFs de muestra reales (ver Engram
  `sdd/pdf-pii-anonymization/document-analysis`)
- ⏳ Próximo paso: `sdd-propose` para fijar el diseño formal, incluyendo storage y la
  decisión sobre señal cruda de ECG.
