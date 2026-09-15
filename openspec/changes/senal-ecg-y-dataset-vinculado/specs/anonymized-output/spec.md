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
