# Salida Anonimizada — Especificación

## Purpose

Emitir el registro estructurado final por tipo de documento, garantizando cero PII en
cualquier campo o log.

## Requirements

### Requirement: Cero PII en el registro de salida
El sistema MUST NOT incluir nombre, DNI ni fecha de nacimiento reales en ningún campo de
ningún registro de salida, para ninguno de los 3 tipos de documento. El registro de salida
MUST incluir `patient_id` en lugar de cualquier identificador directo del paciente.

#### Scenario: Registro de laboratorio sin PII
- GIVEN un documento de laboratorio parseado, con PII detectada y patient_id generado
- WHEN se emite el registro estructurado de salida
- THEN el registro contiene patient_id y la tabla de pruebas
- AND no contiene nombre, DNI, ni fecha de nacimiento en ningún campo

#### Scenario: Registro de ECG y ecocardiograma sin PII
- GIVEN documentos de ECG y ecocardiograma procesados
- WHEN se emiten sus registros de salida
- THEN ninguno de los dos registros contiene nombre, DNI, ni fecha de nacimiento reales

### Requirement: Sin PII en logs ni trazas de error
El sistema MUST NOT escribir PII cruda (nombre, DNI, fecha de nacimiento) en ningún log de
aplicación ni en mensajes de excepción/stack trace, incluso ante errores de emisión.

#### Scenario: Error de emisión no filtra PII
- GIVEN un fallo durante la emisión del registro de salida de un documento
- WHEN se registra el error en el log
- THEN el mensaje de error contiene solo metadata (id de documento, tipo, resultado)
- AND no contiene ningún dato de PII del documento

### Requirement: Formato y storage de la salida — BLOQUEADO
El formato de almacenamiento final del dataset de salida (SQL, NoSQL o híbrido) está
**BLOQUEADO pendiente de sdd-design** (pregunta abierta #1 de la propuesta). Esta
especificación no asume una tecnología de storage concreta; solo exige que, cualquiera sea
el storage elegido, se cumplan los requisitos de cero PII arriba definidos.
