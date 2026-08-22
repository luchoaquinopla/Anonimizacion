# Progreso de aplicación: operación segura y escalable

## Entrega 1 — Corridas durables

Completadas las tareas 1.1–1.4. Se incorporó el dominio de corridas y documentos, persistencia en SQLite/PostgreSQL mediante migración Alembic y repositorio con protección de idempotencia y actualización optimista por versión. No se modificaron workers, portal, bundles, corpus ni parsers.

## Evidencia TDD

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 1.1 | `tests/dominio/test_corridas.py` falló por módulo inexistente. | Dominio y estados nuevos: 2 pruebas pasan. | Cubre flujo completo de corrida y duplicado/reanudación de documento. |
| 1.2 | Cubierta por el RED de 1.1. | Transiciones permitidas incrementan versión; 2 pruebas pasan. | Transiciones declarativas aisladas por tipo de entidad. |
| 1.3 | `tests/salida/test_migraciones.py` falló: faltaban tablas. | Migración `0002` y ORM dejan 4 pruebas verdes. | Se agregaron defaults de auditoría de servidor tras un RED de inserción SQL directa. |
| 1.4 | `tests/ingesta/test_repositorio_corridas.py` falló por repositorio/método inexistente. | Repositorio y actualización optimista: 2 pruebas pasan. | Se centralizó la conversión ORM→dominio y se verificó conflicto de versión. |

## Verificación focalizada

`pytest -q tests/dominio/test_corridas.py tests/ingesta/test_repositorio_corridas.py tests/salida/test_migraciones.py tests/salida/destinos/test_postgres.py`

Pendientes: tareas 2.1–5.2.

## Entrega 2 — Inventario seguro de documentos

Completada la tarea 2.1. `InventariadorDocumentos` limita la exploración a raíces autorizadas, recorre directorios de forma recursiva, omite extensiones no admitidas, rechaza PDFs que exceden el tamaño configurado y conserva una sola entrada por huella de contenido. La huella se calcula por bloques para no cargar PDFs completos en memoria.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 2.1 | `tests/ingesta/test_fuente.py` falló al no existir `InventariadorDocumentos`. | 7 pruebas focalizadas pasan. | Se cubrieron ruta no autorizada, inventario recursivo, extensión ignorada, huella duplicada y límite de tamaño; el cálculo de huella usa bloques de 1 MiB. |

## Verificación focalizada acumulada

- Entrega 1: `pytest -q tests/dominio/test_corridas.py tests/ingesta/test_repositorio_corridas.py tests/salida/test_migraciones.py tests/salida/destinos/test_postgres.py`
- Entrega 2: `pytest -q tests/ingesta/test_fuente.py`

Pendientes: tareas 2.2–5.2.

## Incidencia de verificación

La suite de migraciones falla fuera del alcance de esta entrega porque el worktree ya contiene dos cabeceras Alembic: `0002_corridas_durables` y `0003_tipo_documento_cuarentena`. `command.upgrade(..., "head")` no puede elegir una cabecera. No se modifica esa cadena en la tarea 2.1; requiere una migración de fusión en una entrega dedicada.

## Corrección de seguridad — enlaces simbólicos

La revisión detectó que un enlace simbólico ubicado dentro de una raíz autorizada podía resolver a un archivo externo. Se agregó `_esta_dentro_de_raiz`, aplicada tanto a la raíz solicitada como a cada PDF encontrado. Los destinos fuera de la raíz se omiten antes de leer tamaño o contenido.

| Corrección | RED | GREEN | Refactor / limitación |
|---|---|---|---|
| Enlace simbólico fuera de raíz | La prueba determinista falló por método inexistente. | `tests/ingesta/test_fuente.py`: 8 pasan. | La prueba de enlace real se omite en este Windows por falta del privilegio de symlink; la prueba del destino resuelto cubre la decisión de seguridad. |
