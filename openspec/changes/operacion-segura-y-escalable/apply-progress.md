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
