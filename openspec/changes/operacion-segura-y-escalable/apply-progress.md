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

## Entrega 7 — Portal interno de corridas

Completada la tarea 3.1. Se incorporó una aplicación WSGI interna y sin dependencias nuevas para crear, consultar y reintentar corridas mediante un servicio inyectado. Sólo acepta JSON con una ruta incluida en las raíces configuradas por IT; no recibe archivos, secretos ni devuelve la ruta seleccionada.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 3.1 | `tests/web/test_rutas_corridas.py` falló porque no existía el módulo web. | 2 pruebas focalizadas pasan. | Se cubrieron las tres rutas y se rechazaron PDF, campos de secreto y rutas externas sin invocar el servicio. |

## Verificación focalizada acumulada

- Entrega 7: `pytest -q tests/web/test_rutas_corridas.py` → 2 passed.

Pendientes: tareas 3.2–5.2.

## Entrega 8 — Observabilidad segura

Completada la tarea 3.2. Las métricas operativas ahora exponen cantidades y promedios por etapa, sin muestras individuales. Los motivos de cuarentena se cuentan únicamente si pertenecen al catálogo de códigos del dominio; textos libres y campos no permitidos no llegan al resumen. Las etapas de duración también se limitan al catálogo del pipeline para impedir que un valor accidental con información sensible quede expuesto.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 3.2 | Las pruebas fallaron por ausencia de `resumen_operacional` y `contar_codigos_seguros`; luego la etapa libre no era rechazada. | 47 pruebas focalizadas pasan. | Se cubrieron agregación de documentos/fallos/duraciones, códigos no catalogados con PII y el rechazo de una etapa con PII. |

## Verificación focalizada acumulada

- Entrega 8: `pytest -q tests/observabilidad/test_metricas.py tests/observabilidad/test_bitacora_segura.py` → 47 passed.

Pendientes: tareas 3.3–5.2.

## Entrega 9 — Cola operativa con límites

Completada la tarea 3.3. La cola define una concurrencia configurable limitada entre 1 y 16, prefetch de una tarea para evitar saturar al servidor, confirmación tardía y reenvío si un worker cae. La publicación de tareas usa reintentos con la política de backoff existente. La configuración se vuelve a aplicar al cargar las tareas, para que el modo local sin Redis use correctamente la opción eager incluso cuando otros módulos se importaron antes.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 3.3 | Faltaba `configuracion_cola`; luego el modo eager no respetaba el entorno explícito. | 11 pruebas de trabajadores pasan. | Se cubrieron máximo/mínimo de concurrencia, backpressure, redelivery ante caída, reintentos de publicación y eager sin broker. |

## Verificación focalizada acumulada

- Entrega 9: `pytest -q tests/trabajadores/test_app.py tests/trabajadores/test_tareas.py` → 11 passed.

Pendientes: tareas 3.4–5.2.

## Entrega 10 — Guía de despliegue institucional

Completada la tarea 3.4. Se documentó la instalación base, el catálogo de variables y los controles de permisos, backups, retención y rollback. La guía diferencia la configuración que hoy existe de los requisitos de una operación institucional: no declara un comando de servicio de producción porque aún falta el composition root que conecte portal, corridas, PostgreSQL, Redis y publicación de punta a punta.

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 3.4 | La comprobación documental falló porque no existían `deploy/` ni README. | `tests/deploy/test_documentacion_despliegue.py` pasa. | Se verifican los controles operativos, variables Celery reales y el aviso explícito de que el catálogo no contiene secretos. |

## Verificación focalizada acumulada

- Entrega 10: `pytest -q tests/deploy/test_documentacion_despliegue.py` → 1 passed.

Pendientes: tareas 4.1–5.2.

## Entrega 11 — Corpus sintético base

Completada la tarea 4.1. Se generan localmente PDFs sintéticos de ECG, laboratorio y eco con semilla, junto con un oráculo sin DNI ni nombres. 

| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 4.1 | Faltaba el generador de corpus. | 2 pruebas focalizadas pasan. | Se cubrieron repetibilidad lógica, tres tipos y ausencia de PII en el oráculo. |

Pendientes: tareas 4.2–5.2.

