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

### Requirement: Persistencia de campos adicionales de header
El sistema MUST persistir los campos adicionales de header (cuasi-identificadores
como edad, sexo, peso, talla, superficie corporal, institución u origen, ya sin PII
de médico/técnico) en `estudio.adicionales`, para los 3 tipos de documento (ECG,
laboratorio, ecocardiograma) — no sólo para ECG. `medicion_eco.adicionales` sigue
siendo un campo DISTINTO (medidas del cuerpo del eco sin pivote a columna fija) y no
reemplaza a `estudio.adicionales`.

#### Scenario: Adicionales de header persistidos para los 3 tipos
- GIVEN un registro anonimizado de laboratorio, ECG o ecocardiograma con campos
  adicionales de header (p. ej. edad, peso, institución)
- WHEN se escribe en PostgreSQL
- THEN `estudio.adicionales` queda poblado con esos campos, ya sin PII de
  médico/técnico

#### Scenario: Ningún campo personal en adicionales
- GIVEN un registro anonimizado con adicionales de header
- WHEN se escribe en PostgreSQL
- THEN `estudio.adicionales` nunca contiene nombre crudo de médico derivante,
  médico solicitante ni técnico

### Requirement: Sin PII en logs ni trazas de error
El sistema MUST NOT escribir PII cruda (nombre, DNI, fecha de nacimiento) en ningún log de
aplicación ni en mensajes de excepción/stack trace, incluso ante errores de emisión.

#### Scenario: Error de emisión no filtra PII
- GIVEN un fallo durante la emisión del registro de salida de un documento
- WHEN se registra el error en el log
- THEN el mensaje de error contiene solo metadata (id de documento, tipo, resultado)
- AND no contiene ningún dato de PII del documento

### Requirement: Formato y storage de la salida
El sistema MUST persistir el dataset de salida en PostgreSQL relacional
(`src/anonimizacion/salida/destinos/postgres.py`, esquema gestionado por Alembic en
`migrations/versions/`), como única fuente de verdad. El sistema MAY generar una
exportación derivada a archivo (Parquet + manifiesto) mediante el subcomando `exportar`,
siempre que esa exportación se genere exclusivamente a partir de una lectura de
PostgreSQL, no mute la base, y no se convierta en una fuente de verdad alternativa.

#### Scenario: Salida verificable en PostgreSQL
- GIVEN un episodio anonimizado y aprobado
- WHEN se publica
- THEN sus filas quedan en las tablas relacionales de PostgreSQL (`estudio` y su medición)

#### Scenario: Exportación derivada sin mutar la base
- GIVEN una base con episodios publicados
- WHEN se ejecuta el subcomando `exportar`
- THEN se generan archivos Parquet y un manifiesto a partir de una lectura de PostgreSQL
- AND ninguna fila de PostgreSQL se modifica como efecto de la exportación
- AND la exportación no contiene PII (ver `exportacion-dataset-vinculado`)
