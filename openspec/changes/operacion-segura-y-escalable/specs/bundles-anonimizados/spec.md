# Bundles anonimizados Specification

> **Nota de alcance (2026-09-08)**: el nombre de esta capability ("bundles") quedó
> desactualizado respecto de la decisión de producto vigente — ver el requisito
> retirado más abajo. Se conserva el nombre de directorio para no romper el
> historial de la capability; el contenido activo describe la salida real a
> PostgreSQL.

## Requirements

### Requirement: Publicación de episodio aprobado
El sistema MUST publicar episodios aprobados con identificadores pseudónimos y datos seguros en PostgreSQL.

#### Scenario: Episodio aprobado
- GIVEN un episodio reconciliado y anonimizado
- WHEN se publica
- THEN persiste sus filas en PostgreSQL (estudio, mediciones y cuarentena asociada)
- AND no incluye PDFs, DNI, nombres ni secretos

### Requirement: Separación de originales
El sistema MUST mantener originales y cuarentena fuera del dataset anonimizado.

#### Scenario: Inspección
- GIVEN acceso al dataset
- WHEN se inspecciona
- THEN no contiene PDFs originales

## Requisitos retirados

### ~~Requirement: Bundle pseudónimo (manifiesto de archivo)~~ — RETIRADO 2026-09-08
Redacción original: "El sistema MUST publicar episodios aprobados con
identificadores pseudónimos, **manifiesto** y datos seguros", con el escenario
"crea su **bundle**".

**Por qué se retira**: el manifiesto de archivo (`manifest.json` por episodio)
dependía de `PublicadorBundles`, eliminado en `3410d6c` (`fix(salida): elimina
la ruta de salida Parquet, sin llamador de produccion`) por no tener ningún
llamador de producción — sólo se invocaba desde sus propios tests. La
publicación real de un episodio aprobado escribe directamente en PostgreSQL
(`src/anonimizacion/salida/destinos/postgres.py`); no existe ni se genera un
bundle de archivos ni un manifiesto. El requisito activo equivalente es
"Publicación de episodio aprobado", arriba.

### ~~Requirement: Proyección Parquet idempotente~~ — RETIRADO 2026-09-08
Redacción original: "El sistema MUST generar una proyección trazable sin
duplicar filas", escenario "conserva una única proyección vigente".

**Por qué se retira (decisión de producto)**: la salida del pipeline es la
base de datos relacional, no archivos. `EscritorParquet` y
`PublicadorBundles` sólo se importaban entre sí y desde sus propios tests;
ningún script ni el ejecutor del pipeline los invocaba en producción.
Mantener una segunda salida sin consumidor era superficie donde defectos
viven sin que nadie los vea. Se eliminaron en `3410d6c` junto con sus tests
dedicados y la dependencia `pyarrow`; `b28a261` (`docs: corrige referencias a
Parquet/bundles como si siguieran activos`) corrigió la documentación que
seguía describiéndolos como vigentes. La idempotencia de la fila por episodio
ahora la garantiza la restricción única de `estudio.clave_documento`
(migración `0007_clave_documento`), no una proyección Parquet.

**Verificado en código** (2026-09-08): no queda ninguna ruta de salida
Parquet ni publicador de bundles en `src/` ni en `tests/` — sólo quedan menciones
históricas en comentarios (p. ej. `tests/integracion/test_reprocesar_no_duplica.py`)
y en `openspec/changes/operacion-segura-y-escalable/apply-progress.md`, que
documenta la implementación tal como existió en su momento.
