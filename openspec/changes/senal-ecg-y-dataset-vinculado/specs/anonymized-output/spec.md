# Delta para Salida Anonimizada

## MODIFIED Requirements

### Requirement: Formato y storage de la salida
El sistema MUST persistir el dataset de salida en PostgreSQL relacional
(`src/anonimizacion/salida/destinos/postgres.py`, esquema gestionado por Alembic en
`migrations/versions/`), como única fuente de verdad. El sistema MAY generar una
exportación derivada a archivo (Parquet + manifiesto) mediante el subcomando `exportar`,
siempre que esa exportación se genere exclusivamente a partir de una lectura de
PostgreSQL, no mute la base, y no se convierta en una fuente de verdad alternativa.
(Previously: "No MUST existir ninguna salida adicional a archivo (Parquet u otro formato
analítico): la única salida productiva es PostgreSQL" — prohibición absoluta que la
exportación de dataset vinculado contradice.)

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

## ADDED Requirements

### Requirement: Persistencia de campos adicionales de header
El sistema MUST persistir los campos adicionales de header (cuasi-identificadores
como edad, sexo, peso, talla, superficie corporal, institución u origen, ya sin PII
de médico/técnico) en `estudio.adicionales`, para los 3 tipos de documento (ECG,
laboratorio, ecocardiograma) — no sólo para ECG. `medicion_eco.adicionales` sigue
siendo un campo DISTINTO (medidas del cuerpo del eco sin pivote a columna fija) y no
reemplaza a `estudio.adicionales`.

(Hallazgo entrega 2b: `_escribir_laboratorio`/`_escribir_eco` descartaban en
silencio `registro.adicionales`, violando la decisión de comité 2026-09-07 que
exige conservar estos cuasi-identificadores para los 3 tipos.)

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
