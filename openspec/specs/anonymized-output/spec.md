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

### Requirement: Formato y storage de la salida
El sistema MUST persistir el dataset de salida en PostgreSQL relacional
(`src/anonimizacion/salida/destinos/postgres.py`, esquema gestionado por Alembic en
`migrations/versions/`). No MUST existir ninguna salida adicional a archivo (Parquet u
otro formato analítico): la única salida productiva es PostgreSQL.

**Resuelto 2026-09-08** (originalmente BLOQUEADO pendiente de sdd-design, pregunta abierta
#1 de la propuesta): el equipo evaluó en paralelo una salida a Parquet/bundles de archivo
(`EscritorParquet`, `PublicadorBundles`), pero esos módulos nunca tuvieron un llamador de
producción y se eliminaron en `3410d6c` (`fix(salida): elimina la ruta de salida Parquet,
sin llamador de produccion`) por ser superficie sin consumidor. La decisión de producto es
que la salida es la base de datos, no archivos — ver también el requisito retirado en
`openspec/changes/operacion-segura-y-escalable/specs/bundles-anonimizados/spec.md`.

#### Scenario: Salida verificable en PostgreSQL
- GIVEN un episodio anonimizado y aprobado
- WHEN se publica
- THEN sus filas quedan en las tablas relacionales de PostgreSQL (`estudio` y su medición)
- AND no se genera ningún archivo Parquet, manifiesto ni bundle
