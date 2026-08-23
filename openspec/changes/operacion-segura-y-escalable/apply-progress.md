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

Completada la tarea 4.1. Se generan localmente PDFs sintéticos de ECG, laboratorio y eco con semilla, junto con un oráculo sin DNI ni nombres.`r`n
| Tarea | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 4.1 | Faltaba el generador de corpus. | 2 pruebas focalizadas pasan. | Se cubrieron repetibilidad lógica, tres tipos y ausencia de PII en el oráculo. |

Pendientes: tareas 4.2–5.2.

## Corrección de fidelidad — Corpus sintético de plantillas

Se recalibraron las tres plantillas contra las referencias locales autorizadas, inspeccionadas sólo por geometría, paginación y etiquetas estructurales. No se copió, versionó ni registró contenido identificatorio de esas referencias. El corpus ahora reproduce el contrato que necesitan los parsers: ECG apaisado de una página con aviso tolerado, medidas, grilla y trazado explícitamente no clínico; laboratorio A4 de tres páginas con encabezado repetido y tablas por secciones; y ecocardiograma de dos páginas con encabezado, tabla de medidas y bloques de texto libre.

| Tarea / corrección | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| 4.1, fidelidad de layout | Dos pruebas nuevas fallaron: el ECG se emitía A4 y laboratorio/eco sólo tenían una página. | `tests/fixtures/test_pdf_sintetico_corpus.py` pasa 5 pruebas. | Se aisló el dibujo repetible de tablas, encabezados y pie de página; se probaron geometría, orden de etiquetas, paginación, secciones, marcador sintético y ejecución sin red. |

## Fidelidad comprobada y límite conocido

- ECG: 792×612, una página, etiquetas `12SL`, `PID / NAME MISMATCH`, bloque de medidas, calibración, grilla y seis trazos sintéticos no clínicos.
- Laboratorio: 595×842, tres páginas, encabezado repetido, columnas de determinación/resultado/unidades/referencia y secciones HEMATOLOGIA, QUIMICA CLINICA e IONOGRAMA.
- Ecocardiograma: 616×862, dos páginas, campos de encabezado, tabla de medidas y secciones MOTILIDAD SEGMENTARIA, VALVULAS, DOPPLER y CONCLUSIONES.
- Todas las plantillas usan exclusivamente textos, identificadores y valores ficticios generados localmente; el oráculo no conserva nombre ni DNI y el generador no requiere red.

Pendiente: calibrar tipografías, espaciados finos y variantes de layout contra una colección institucional de originales previamente anonimizados y autorizados. Esta tarea no prueba aún decisiones clínicas ni reemplaza la prueba masiva de 4.2–4.3.

## Corrección de cobertura — Campos y secciones de referencias autorizadas

Se realizó un inventario seguro campo por campo: las tres referencias locales se consultaron exclusivamente para comprobar etiquetas, geometría y secciones; no se conservaron valores ni fragmentos de texto. La matriz versionada `tests/fixtures/matriz_cobertura_sinteticos.md` registra qué parte del contrato cubre cada plantilla y sus omisiones deliberadas.

| Corrección | RED | GREEN | REFACTOR / triangulación |
|---|---|---|---|
| Cobertura contractual de campos | La nueva prueba falló porque faltaban campos de cabecera y secciones de laboratorio/eco. | `tests/fixtures/test_pdf_sintetico_corpus.py` pasa 6 pruebas. | El contrato verifica presencia y orden de secciones; los helpers existentes conservan cabecera, tabla y paginación sin duplicar lógica. |

La ampliación agrega únicamente etiquetas y datos ficticios relevantes para detección, parseo, anonimización o reconciliación: cabecera demográfica/técnica y métricas del ECG; datos administrativos y HEMOSTASIA para laboratorio; y cabecera, medidas, válvulas, pericardio y firma profesional para eco. La señal ECG no se declara como dato clínico: permanece como grilla y trazado sintético para validar geometría visual.

Verificación visual: se regeneraron e inspeccionaron las seis páginas de `tmp/muestras_fieles/`. Pendientes 4.2–5.2.

## Compuerta 1:1 — Laboratorio

Se incorporó una calibración reproducible que ejecuta extracción nativa, detección de tipo, parseo, normalización estructural y reconciliación sobre cualquier PDF de laboratorio. El original autorizado se usó sólo localmente para derivar un contrato versionable de etiquetas, conteos y estados; CI ejecuta ese contrato exclusivamente contra el sintético.

| Tarea | Safety net | RED | GREEN | Triangulación / refactor |
|---|---|---|---|---|
| 4.1a, compuerta de laboratorio | 40 pruebas focalizadas pasaban antes del cambio. | La compuerta no existía; después mostró que el sintético fallaba en parseo por etiquetas y formatos de fecha/petición incompatibles. | 8 pruebas de calibración/fixtures pasan y la comparación local alcanza 1.0 en campos, secciones y determinaciones para ambos documentos. | Se separaron resumen seguro, contrato y comparación; dos semillas verifican comportamiento y ausencia de valores identificatorios. |

### Diferencias iniciales y corrección

- El original era detectado y parseado; el sintético era detectado pero quedaba en cuarentena durante parseo.
- La primera versión alineó cabecera, fechas, petición y tabla multipágina, pero dejó una cuarentena reproducible por diferencias entre parser e inventario independiente.
- Esa cuarentena motivó la corrección posterior documentada a continuación; no se tomó como criterio de éxito definitivo.

## Corrección de la compuerta — Laboratorio aprobado de punta a punta

La calibración anterior reproducía una cuarentena en vez de demostrar un flujo utilizable. Se corrigió sin relajar la cobertura: parser y reconciliador mantienen inventarios independientes, pero comparten la regla estructural de cualitativos y la canonicalización `IONOGRAMA SERICO` → `IONOGRAMA`. El parser conserva la subsección entre páginas, descarta encabezados repetidos y mantiene página/ordinal de cada fila.

| Corrección | RED | GREEN | Triangulación |
|---|---|---|---|
| Cualitativos, alias y continuidad | 4 fallas contractuales confirmaron omisión, alias divergente y absorción de narrativa; 2 fallas adicionales confirmaron pérdida de sección y falso positivo de petición. | 40 pruebas de parser/reconciliación y 48 focales acumuladas pasan. | La regla acepta celdas breves en mayúsculas sin enumerar resultados, rechaza prosa y conserva asociación ordinal multipágina. |
| Calibración original/sintético | El contrato previo esperaba cuarentena y no ejecutaba realmente política PII ni construcción anonimizada. | Ambos finalizan aprobados con 36 resultados numéricos, 6 secciones, 29 determinaciones únicas, 34 unidades y 33 referencias. | La compuerta ejecuta clasificación PII y construcción del registro; verifica cinco campos retirados y conteos por categoría, nunca valores. |

Reporte local seguro: `tmp/calibracion_laboratorio/reporte_seguro.json` (no versionado). No queda una nueva cuarentena de laboratorio. La compuerta global permanece pendiente y bloquea 4.2 hasta completar ECG y ecocardiograma (4.1b–4.1c).

## Compuerta 1:1 — Ecocardiograma aprobado de punta a punta

La referencia autorizada se inspeccionó sólo de forma local y se resumió mediante etiquetas, conteos, procedencia y estados. El original reveló que una sección Doppler empieza en la página 1 y continúa después del encabezado repetido de la página 2. El parser incorporaba ese boilerplate —incluidos campos identificatorios— al texto clínico y el reconciliador no podía anclar la evidencia. También capturaba columnas vecinas al validar el nombre del header.

| Tarea | Safety net | RED | GREEN | Triangulación / refactor |
|---|---|---|---|---|
| 4.1c, compuerta de eco | 47 pruebas de parser, reconciliación y fixtures pasaban. | La compuerta faltaba; el caso multipágina mostró pie/header dentro de `FLUJO PULMONAR`, y el header en una fila falló por arrastrar columnas. | 51 pruebas focales pasan; original y sintético finalizan aprobados hasta PII/anonimización. | Se filtró sólo boilerplate declarado, se deduplicó el inventario de headers repetidos y se conservó el anclaje estricto de texto clínico. |

La equivalencia exacta cubre 10 medidas en su orden (7 numéricas y 3 textuales), 12 secciones en su orden, unidades, páginas de medidas/secciones, firma en página 2, campos estructurados, conteos PII y decisión final. El sintético conserva dos páginas, tabla doble y continuidad de `FLUJO PULMONAR`, siempre con datos ficticios. Reporte local seguro: `tmp/calibracion_ecocardiograma/reporte_seguro.json` (no versionado).

Verificación final: 51 pruebas focales y la suite completa (`409 passed, 1 skipped`) sin regresiones; el único omitido requiere privilegios de enlaces simbólicos en Windows.

La compuerta global sigue bloqueada únicamente por ECG (4.1b); 4.2 no debe comenzar antes de completarla.

## Compuerta 1:1 — ECG aprobado de punta a punta

La referencia autorizada se procesó sólo localmente y se resumió sin valores. El original atraviesa detección, parseo, reconciliación, política PII y construcción anonimizada con cinco métricas textuales extraíbles. El sintético anterior era detectado como ECG, pero su cabecera idealizada no correspondía al layout posicional Mortara y terminaba en `parseo_incompleto`.

| Tarea | Safety net | RED | GREEN | Triangulación / refactor |
|---|---|---|---|---|
| 4.1b, compuerta ECG | 21 pruebas de parser, reconciliación y fixture pasaban. | La compuerta no existía y el diagnóstico confirmó la cuarentena del sintético durante parseo. | La compuerta y el fixture recalibrado pasan; original y sintético finalizan aprobados hasta PII/anonimización. | Dos semillas y una cabecera incompleta verifican el contrato; 25 pruebas focales cubren parser, reconciliación, aviso tolerado y corpus. El layout se renderizó para separar visualmente métricas y trazado. |

La equivalencia segura cubre los campos de cabecera, cinco métricas en orden (`Vent. rate`, PR, QRS, QT/QTc y P-R-T), su normalización numérica escalar/par/triple, procedencia en página 1, `PID / NAME MISMATCH`, categorías y conteos PII y decisión final. La imagen de trazado queda declarada fuera del contrato clínico: sólo se prueba la presencia de una grilla y figura no clínica, nunca equivalencia de señal o interpretación médica. Reporte local seguro: `tmp/calibracion_ecg/reporte_seguro.json` (no versionado).

Verificación final: 25 pruebas focales y la suite completa (`413 passed, 1 skipped`) sin regresiones; el único omitido requiere privilegios de enlaces simbólicos en Windows. Con laboratorio, ecocardiograma y ECG aprobados, la compuerta global 4.1a–4.1c queda completa. La prueba masiva 4.2 continúa pendiente y no se inició en esta entrega.

## Entrega 12 — Corpus piloto adversarial

Se incorporó una etapa intermedia de 50 casos deterministas antes de las pruebas de 1k/10k/100k. Los PDFs se generan sólo en el temporal de pytest y atraviesan inventario por huella, extracción, detección, parseo, reconciliación, política PII, coordinación de episodios, anonimización y un destino seguro en memoria. La resolución de identidad usa un adaptador determinista del test para aislar el comportamiento del lote sin conservar identificadores del PDF en el oráculo.

| Tarea | Safety net | RED | GREEN | Triangulación / refactor |
|---|---|---|---|---|
| 4.2a, piloto adversarial | 31 pruebas relevantes pasaban; 1 omitida por privilegios de symlink en Windows. | El test falló porque no existía `tests.fixtures.corpus_piloto`; luego tres ECG válidos expusieron `evidencia_ambigua` por repetir una cifra fuera de su campo. | El piloto produce 40 episodios aprobados, 120 documentos publicados y 29 cuarentenas esperadas. | Dos corridas completas con la misma semilla coinciden; la red se bloquea, el oráculo no contiene PII y cinco copias se omiten por huella. La asociación estructural ahora prevalece sobre coincidencias numéricas incidentales. |

Evidencia final del piloto: 154 PDFs de entrada, 149 documentos inventariados, 8 fallos de asociación ambigua, 19 por estudios faltantes y 2 PDFs corruptos. Las 17 pruebas focales pasan y la suite completa queda en `416 passed, 1 skipped`; el único omitido requiere privilegios de enlaces simbólicos en Windows. Este resultado valida decisiones y conteos funcionales, no capacidad: los escalones 1k/10k/100k de 4.3 siguen pendientes.

### Corrección posterior a auditoría del piloto

La verificación de privacidad ahora captura en memoria los valores sintéticos transitorios de cada generación —incluidos nombre, DNI, nacimiento, profesionales e identificadores de petición/estudio— y los compara contra los 120 `RegistroAnonimizado` reales. Sólo persiste el conteo de 572 comprobaciones, nunca sus valores. Una prueba de control demuestra que el detector reconoce fugas de todas las categorías.

El RED ampliado encontró que el nombre del técnico ECG sobrevivía dentro de `adicionales`. El constructor final ahora retira también esa clave de personal; el piloto recalibrado vuelve a cero coincidencias sin reducir el conjunto inspeccionado.

También se agregaron regresiones Eco: una asociación estructurada válida prevalece ante una repetición incidental y dos filas estructuradas iguales siguen en cuarentena por la cobertura independiente. Verificación final corregida: 33 pruebas focales y suite completa con `419 passed, 1 skipped`.

## Entrega 13 — Primer escalón de carga de 1.000 PDFs

Se agregó un runner reproducible que reutiliza las plantillas calibradas y el pipeline del piloto. El plan contiene 333 casos y exactamente 1.000 PDFs de entrada: 320 completos, 4 en el límite de siete días, 3 separados por ocho días, 3 faltantes, 2 ambiguos, 1 corrupto y 2 duplicados intencionales. Cada generación usa semilla/fecha propias; los duplicados no sustituyen el volumen.

| Tarea | Safety net | RED | GREEN | Triangulación / refactor |
|---|---|---|---|---|
| 4.3a, carga 1k | Las 3 pruebas del piloto pasaban en 70,26 s. | Primero faltaba `tests.carga.ejecutar_corpus`; la auditoría posterior exigió CLI reejecutable, oráculo completo y métricas no ambiguas. | Cinco pruebas cubren plan/oráculo exactos, desvío rechazado, corrida real pequeña y dos ejecuciones aisladas con reporte agregado. | La generación/ejecución común se extrajo del piloto; memoria y throughput explicitan su denominador/alcance y 10k/100k quedan fuera. |

La ejecución corregida produjo 1.000 PDFs de entrada y 998 documentos únicos: 324 episodios/972 documentos aprobados; 26 cuarentenas esperadas (`cobertura_ambigua`: 8, `cobertura_incompleta`: 17, `parseo_incompleto`: 1), 0 fallos inesperados, 2 duplicados, 0 reintentos y 0 PII. Duró 226,541137 s, con 4,414 PDFs de entrada/s, 4,405 únicos/s y pico lifetime de 145.432.576 bytes. El workspace conserva además 1.005 PDFs de staging, por lo que el doble I/O forma parte del tiempo medido. Cada corrida usa un UUID y el reporte estable agrega historiales.

La medición ejecuta extracción, detección, parser, reconciliación, coordinación y constructor reales. Usa motor PII offline y resolutor determinista; no mide Presidio-spaCy, HMAC real, Celery/Redis, PostgreSQL ni storage productivo. Los literales sintéticos efímeros se contrastan contra los registros finales, sin presentar ese control como evaluación del NER institucional.

## Entrega 14 — Escalón de carga de 10.000 PDFs

El runner común ahora genera perfiles mediante una composición base y escala el oráculo, sin duplicar el pipeline ni los conteos. El perfil 10k conserva la proporción del escalón 1k: 3.200 completos, 40 en el límite de siete días, 30 separados por ocho días, 30 faltantes, 20 ambiguos, 10 corruptos y 20 duplicados intencionales. La entrada local `tests/carga/ejecutar_corpus_10000.py` no forma parte de CI.

| Tarea | RED | GREEN | Ejecución / triangulación |
|---|---|---|---|
| 4.3b, carga 10k | El contrato falló al importar el perfil y el oráculo 10k inexistentes. | Seis pruebas focales pasan y validan composición, conteos, códigos y deduplicación esperada. | La corrida exacta aprobó el oráculo completo y mantuvo aislamiento UUID, PII efímera, cuarentenas esperadas y fallos inesperados separados. |

Preflight recalculado al migrar el reporte: 888.964.816.896 bytes de disco y 6.227.922.944 bytes de RAM disponibles; 1.085.851.860 bytes de disco para staging + entrada, 1.454.325.760 bytes de memoria y 2.265,41137 s estimados. La ejecución produjo 10.000 PDFs de entrada, 10.050 PDFs de staging y 9.980 documentos únicos: 3.240 episodios/9.720 documentos aprobados; 260 cuarentenas esperadas (`cobertura_ambigua`: 80, `cobertura_incompleta`: 170, `parseo_incompleto`: 10), 0 fallos inesperados, 20 duplicados, 0 reintentos y 0 PII literal en salida. Duró 2.874,229822 s, con 3,479 PDFs de entrada/s, 3,472 únicos/s y pico lifetime de 315.772.928 bytes. El reporte seguro conserva el preflight agregado y su estado aprobado.

### Corrección semántica de métricas de carga

La revisión confirmó que `generados/` y `entrada/` coexisten durante la corrida. Los campos del reporte se renombraron a `pdfs_entrada` y `throughput_pdfs_entrada_segundo`, y se agregó `pdfs_staging_generados`; no se presenta la cantidad de entrada como total físico del workspace. El preflight reproducible considera ambas áreas y persiste sólo espacio/memoria disponibles, estimaciones de disco/memoria/tiempo y estado aprobado. Los reportes locales anteriores se migraron de forma atómica sin repetir la ejecución 10k.

| Corrección | RED | GREEN / migración |
|---|---|---|
| Semántica entrada/staging y preflight | Cuatro pruebas fallaron al exigir campos separados y preflight; un RED adicional confirmó que el resumen piloto todavía exponía `archivos_en_disco`. | 10 pruebas de carga/piloto pasan. Los reportes 1k/10k fueron migrados y validados localmente, sin valores sensibles ni nueva corrida 10k. |

El alcance técnico sigue siendo el mismo que en 1k: extracción, detección de tipo, parser, reconciliación, coordinación y constructor reales; motor PII offline y resolutor determinista; sin medir Presidio-spaCy, HMAC real, Celery/Redis, PostgreSQL ni storage productivo. El escalón 100k queda pendiente y nunca debe ejecutarse en CI.
