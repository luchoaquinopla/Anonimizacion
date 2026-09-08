# Detección de PII — Especificación

## Purpose

Identificar nombre, DNI, fecha de nacimiento e IDs internos potencialmente
re-identificantes dentro del documento parseado, de forma 100% offline.

## Requirements

### Requirement: Detección híbrida NER + regex, 100% offline
El sistema MUST detectar nombre, DNI y fecha de nacimiento usando un enfoque híbrido:
Presidio + spaCy `es_core_news_lg` para NER, más un recognizer custom de formato de DNI
argentino. El sistema MUST NOT realizar ninguna llamada de red durante la detección.

#### Scenario: Detección de DNI en header de laboratorio
- GIVEN un header de laboratorio con el campo DNI en formato numérico argentino
- WHEN se ejecuta la detección de PII
- THEN el DNI se identifica correctamente como entidad PII

#### Scenario: Sin llamadas de red
- GIVEN el proceso de detección de PII ejecutándose sin acceso a internet
- WHEN se detecta PII en cualquier documento
- THEN la detección completa exitosamente sin ningún intento de conexión externa

### Requirement: IDs internos tratados como cuasi-identificadores
El sistema MUST tratar Nº de Petición, Nº de Estudio e ID interno de estudio de ECG como
cuasi-identificadores PII, con el mismo tratamiento de anonimización que nombre/DNI, por
su potencial de re-identificación vía el sistema del instituto.

#### Scenario: Nº de Petición anonimizado
- GIVEN un registro de laboratorio con Nº de Petición "12345"
- WHEN se genera la salida anonimizada
- THEN el Nº de Petición original no aparece en el registro de salida

### Requirement: Marcado de detecciones de baja confianza
El sistema SHOULD marcar como revisión manual pendiente cualquier detección de PII de baja
confianza, en lugar de descartarla silenciosamente como no-PII (mitigación de falsos
negativos, riesgo R2).

#### Scenario: Nombre con baja confianza de NER
- GIVEN un texto donde el modelo NER detecta un posible nombre con confianza baja
- WHEN se ejecuta la detección de PII
- THEN el documento se marca para revisión en lugar de emitirse como si no tuviera PII

### Requirement: Política sobre nombre del médico derivante/informante
El nombre del médico derivante/solicitante/informante es PII de un profesional, no del
paciente. El sistema MUST pseudonimizarlo en un namespace propio (`id_medico`), separado
del namespace del paciente y nunca vinculado al mismo grafo de identidad.

**Resuelto** (originalmente BLOQUEADO pendiente de sdd-design, pregunta abierta #3 de la
propuesta; ver `design.md`, decisión Q3, y `src/anonimizacion/pii/politica.py`,
`NAMESPACE_MEDICO`): el nombre del médico se recolecta tanto de campos de header
(`medico_derivante`/`medico_solicitante`) como de la firma al pie del informe, y se
pseudonimiza bajo `id_medico` con el mismo mecanismo HMAC que `id_paciente`, pero en un
namespace independiente.

#### Scenario: Nombre del médico pseudonimizado en namespace propio
- GIVEN un documento con el nombre del médico derivante en su header o en la firma
- WHEN se ejecuta la detección y clasificación de PII
- THEN el nombre se pseudonimiza como `id_medico`
- AND ese identificador nunca se mezcla ni se vincula con `id_paciente`
