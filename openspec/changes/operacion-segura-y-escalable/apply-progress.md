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

## Corrección de infraestructura — fusión Alembic

Se detectaron dos ramas de migración independientes desde `0001_esquema_inicial`: una de corridas durables y otra de metadata segura de cuarentena. Se agregó `0004_fusion_corridas_cuarentena`, una migración de fusión sin cambios de esquema que obliga a aplicar ambas ramas antes de continuar.

| Corrección | RED | GREEN | Refactor / triangulación |
|---|---|---|---|
| Cabeceras Alembic múltiples | La prueba de una única cabecera falló con dos revisiones. | `alembic heads` muestra solo `0004_fusion_corridas_cuarentena`; `tests/salida/test_migraciones.py` pasa 5 pruebas. | La migración no contiene DDL y preserva los dos historiales existentes. |

## Entrega 3 — Coordinación de episodios

Completada la tarea 2.2. El coordinador agrupa documentos del mismo paciente con una ancla de hasta siete días, exige un ECG, un laboratorio y un ecocardiograma por episodio, y evita publicar decisiones incompletas hasta el cierre de la corrida. Los tipos repetidos dentro de un candidato se tratan como asociación ambigua y quedan en cuarentena.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 2.2 | `tests/pipeline/test_coordinador_episodios.py` falló porque el módulo no existía. | 4 pruebas focalizadas pasan. | Cubre ventana de 7 días, separación a 8 días, empate por tipo, estudios faltantes y cierre de corrida. |

Pendientes: tareas 2.3–5.2.

## Entrega 4 — Extracción persistente por documento

Completada la tarea 2.3. Las tareas de worker ahora pueden ejecutar extracción mínima y completa como etapas separadas, actualizar el estado durable del documento y reanudar sin volver a ejecutar una extracción mínima ya confirmada. Ninguna de estas tareas publica resultados: la publicación continúa fuera de este corte.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 2.3 | Las pruebas fallaron al no existir la configuración ni la tarea de extracción persistente. | 2 pruebas nuevas pasan. | Se cubrieron reinicio sin duplicar extracción mínima y extracción completa posterior a asociación; el fixture reinicia dependencias globales entre pruebas. |

Pendientes: tareas 2.4–5.2.

## Entrega 5 — Bundles anonimizados

Completada la tarea 2.4. Los bundles se publican en una carpeta temporal y se renombran al destino sólo después de escribir el manifiesto. El manifiesto contiene únicamente identificadores pseudónimos, versión y tipos de estudio. La proyección Parquet por episodio reemplaza su archivo temporalmente para conservar una única fila vigente.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 2.4 | Las pruebas fallaron por ausencia del publicador. | 2 pruebas focalizadas pasan. | Cubre publicación atómica, manifiesto sin PII y reemplazo de la fila Parquet. |

Pendientes: tareas 2.5–5.2.

## Entrega 6 — Integración segura por episodio

Completada la tarea 2.5. `EjecutorPipeline` puede recibir el coordinador durable: una vez que cada documento pasó su reconciliación, la coordinación decide los episodios completos antes de construir registros anonimizados o escribir salida. Los estudios faltantes y asociaciones ambiguas quedan en cuarentena con códigos seguros; los lotes previos conservan su vínculo histórico mientras no se inyecte el coordinador nuevo.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 2.5 | La prueba E2E falló porque `EjecutorPipeline` no aceptaba `coordinar_episodios`. | 17 pruebas de ejecutor/coordinador pasan; 111 de pipeline y reconciliación pasan. | Se cubrieron un episodio incompleto sin anonimización/publicación y uno completo que se emite tras reconciliar sus tres estudios; el adaptador convierte el resultado durable al contrato de salida existente. |

## Verificación focalizada acumulada

- Entrega 6: `pytest -q tests/pipeline/test_ejecutor.py tests/pipeline/test_coordinador_episodios.py` → 17 passed.
- Integración: `pytest -q tests/reconciliacion tests/pipeline` → 111 passed.

Pendientes: tareas 3.1–5.2.
