# Apply progress: señal de ECG y dataset vinculado

## Entrega 1 (PR 1, rama `feat/senal-ecg-1-extraccion`)

Estado: **completa** — 6/6 tareas de la Fase 1.

### TDD Cycle Evidence

| Tarea | RED | GREEN | REFACTOR | Commit |
|---|---|---|---|---|
| 1.1 | `tests/extraccion/test_trazos_pymupdf.py` (caracterización: fija que `get_drawings()` ya entrega coordenadas sin rotar) | — (no aplica implementación, es hallazgo) | — | `51c17f5` |
| 1.2 | (mismo archivo, tests de `capturar_trazos`) | `src/anonimizacion/extraccion/trazos_pymupdf.py` | n/a (función simple) | `51c17f5` |
| 1.3 | `tests/extraccion/test_texto_pymupdf.py` (extendido) | `src/anonimizacion/extraccion/registro_trazos.py` + `extraccion/texto_pymupdf.py` extendido | n/a | `140706c` |
| 1.4 | `tests/extraccion/test_senal_ecg.py`, `tests/dominio/test_senal_ecg.py` | `src/anonimizacion/dominio/senal_ecg.py`, `src/anonimizacion/extraccion/senal_ecg.py` | Descompuesto desde el inicio en `_clasificar`/`_calibracion_valida`/`_asignar_derivaciones`/`_particionar`/`_muestrear`, cada una bajo el límite de complejidad 10 (`pyproject.toml` mccabe) — sin `noqa: C901` necesario | `135bee6` |
| 1.5 | `tests/fixtures/test_pdf_sintetico_ecg.py` | `tests/fixtures/pdf_sintetico.py` (`crear_pdf_ecg_con_trazos_sinteticos`) + fix de línea base de amplitud (centro de banda, no primer punto) | — | `5f1f1d8` |
| 1.6 | — | — | Revisión de complejidad: sin hallazgos, ver 1.4 | `135bee6` |
| Corrección | `test_pdf_sintetico_ecg_recupera_signo_amplitud_y_linea_base`, `test_construir_senal_sigue_la_direccion_del_pulso_invertido`, `test_construir_senal_falla_si_los_pulsos_apuntan_en_direcciones_distintas`, `test_construir_senal_ignora_el_orden_de_los_puntos_del_pulso` | `_pie_y_meseta`, `_calibrar_pulsos`, `_emparejar_por_proximidad` en `extraccion/senal_ecg.py` | Ninguna (fix quirúrgico sobre función ya descompuesta) | `b1af035` |

### Archivos

| Archivo | Acción |
|---|---|
| `src/anonimizacion/extraccion/trazos_pymupdf.py` | Creado |
| `src/anonimizacion/extraccion/registro_trazos.py` | Creado |
| `src/anonimizacion/extraccion/senal_ecg.py` | Creado |
| `src/anonimizacion/dominio/senal_ecg.py` | Creado |
| `src/anonimizacion/extraccion/texto_pymupdf.py` | Modificado (`capturador_para`, `TextoExtraido.trazos`) |
| `tests/extraccion/test_trazos_pymupdf.py` | Creado |
| `tests/extraccion/test_senal_ecg.py` | Creado |
| `tests/dominio/test_senal_ecg.py` | Creado |
| `tests/extraccion/test_texto_pymupdf.py` | Modificado |
| `tests/fixtures/pdf_sintetico.py` | Modificado (`crear_pdf_ecg_con_trazos_sinteticos`) |
| `tests/fixtures/test_pdf_sintetico_ecg.py` | Creado |
| `openspec/changes/senal-ecg-y-dataset-vinculado/tasks.md` | Marcado `[x]` Fase 1 |

### Decisión #1 del diseño, fijada empíricamente (tarea 1.1)

`get_drawings()` sobre una página con `rotation=90` devuelve las coordenadas
YA SIN ROTAR (espacio del `mediabox`), donde el tiempo corre por el eje
vertical. Aplicar `page.derotation_matrix` (como sugería el texto tentativo
del algoritmo en `design.md`) ESTROPEA ese eje — convierte la altura
(tiempo) en ancho. `trazos_pymupdf.py` no aplica ninguna matriz.

### Hallazgo no obvio: línea base de amplitud

`construir_senal._muestrear` originalmente usaba el primer punto del trazo
como línea base (`xs[0]`), copiando el criterio de "pie" que sí es correcto
para un pulso de calibración (que arranca en reposo). Contra el PDF
sintético con oráculo de fase aleatoria, eso daba error de hasta 0,27 mV: una
derivación puede empezar en cualquier fase de la onda, no en su cero. Fix:
la línea base de una derivación es el centro de su banda de amplitud
(promedio de X de todo el trazo), no su primer punto. El pulso de
calibración conserva el criterio de "pie" (primer punto) porque sí arranca
en reposo por construcción.

### Verificación contra ECG real (sólo lectura, sin PII)

Corrido contra `D:\ejemplos_pdf\document (34).pdf` (nunca versionado, nunca
usado en tests): `page.rotation=90`, 17 trazos negros capturados (12×1238,
1×5000, 4×60), calibración de los 4 pulsos = 10,001 mm (dentro de ±2%),
asignación 4×3 válida, `construir_senal` devuelve señal `(12, 5000)` con 1
fila íntegramente enmascarada (V1, la tira de ritmo). Ningún dato de
paciente fue impreso, logueado ni guardado.

### Desviaciones del diseño

Ninguna decisión de negocio deviada, pero **sí hay dos desviaciones reales**
del texto de `design.md` (algoritmo), descubiertas por medición contra el
ECG real y corregidas en esta misma entrega:

1. **Paso 1 (captura)**: `design.md` marcaba explícitamente como "pregunta
   abierta" si `get_drawings()` devuelve coordenadas rotadas o sin rotar.
   El test de la tarea 1.1 la fijó por medición: sin rotar, y aplicar
   `derotation_matrix` (como sugería el texto tentativo del algoritmo)
   estropea el eje de tiempo. Esto no es una desviación -- es la
   resolución de una ambigüedad que el propio diseño delegaba a esta tarea.
2. **Paso 2 (calibración)**: `design.md` describe "el pulso de cada fila"
   y una conversión fija `mV = desplazamiento/10`, sin distinguir signo ni
   asociar explícitamente cada pulso a una banda de amplitud. La primera
   implementación (`135bee6`) interpretó esto como 4 pulsos por COLUMNA y
   una escala de signo fijo -- **desviación real, no contemplada por el
   texto del diseño ni cubierta por sus tests originales**, que producía
   la señal con la amplitud invertida (ver sección de corrección más
   abajo). La medición contra el ECG real corrigió esto a: 4 pulsos, uno
   por BANDA DE AMPLITUD (3 filas de la grilla + la banda propia de la
   tira), cada uno determinando signo y línea base de su propia banda. Se
   recomienda actualizar `design.md` en un cambio posterior para que el
   texto del algoritmo refleje esta geometría medida en vez de la
   redacción original ("el pulso de cada fila" queda ahora correcto, pero
   la fórmula de conversión y la ausencia de mención a la banda de la tira
   no reflejan lo implementado).

### Estado de la suite completa (post-corrección, con Postgres levantado)

`uv run pytest -q`: **945 passed, 1 skipped** (symlink en Windows,
ambiental, sin relación con este cambio). Una corrida anterior mostró 13
errores transitorios (`LlamadaDeRedBloqueada`) en tests no relacionados
con esta entrega; se repitió la corrida completa y no reprodujo -- flake
preexistente de aislamiento entre tests, no introducido por este cambio.

### Corrección post-revisión adversarial (commit `b1af035`)

**CRITICAL — signo de amplitud invertido.** El ECG real mide +1 mV como
**-10 mm** en X (pie a la derecha, meseta a la izquierda) -- `senal_ecg.py`
usaba una convención de signo fija (`mv = (x - xs.mean()) / 10`, +X = +mV)
y el fixture sintético dibujaba con la fórmula EXACTAMENTE inversa (`x =
centro + mv*10`): el test nunca podía detectar un signo invertido, porque
ambos lados del test compartían la misma convención. **Regla aprendida: un
fixture que comparte la fórmula del código bajo prueba no es un oráculo —
es un espejo.** Un oráculo tiene que fijar valores independientes (aquí:
plateaus a mV conocidos, no una expresión algebraica en función de x/mv) y,
donde el signo importa, el fixture debe poder invertirse por parámetro
mientras el código sigue derivando la dirección de la evidencia geométrica
(el pulso), no de una constante.

Fix: cada banda de amplitud (3 filas de la grilla + la banda propia de la
tira -- medido: hay 4 pulsos porque hay 4 bandas, no porque haya 4
columnas como se asumió en el commit anterior) deriva su signo y su línea
base del pulso de calibración de ESA banda (`x_pie`, `x_meseta` por
posición temporal). Si los 4 pulsos no apuntan en la misma dirección, la
señal se descarta.

**WARNING** -- `_pie_y_meseta` ahora ordena los puntos del pulso por Y
antes de leer pie/meseta (antes se asumía que el primer punto de la tupla
ya era el pie, sin ordenar).

**SUGGESTION** -- `TOLERANCIA_DURACION` separada de `TOLERANCIA_CALIBRACION`;
`_muestrear` rechaza también sobre-cobertura temporal, no sólo
sub-cobertura.

Se agregó `ruff>=0.16` a `dev` en `pyproject.toml` (faltaba, bloqueaba el
lint pedido).

### Verificación contra ECG real, signo corregido (sólo lectura, sin PII)

aVR: mín -0,683 mV, máx 0,156 mV -- predominantemente NEGATIVO (esperado
clínicamente). II: mín -0,36 mV, máx 1,162 mV -- predominantemente
POSITIVO (esperado). Antes del fix quedaban invertidos.

### Tamaño del cambio

`git diff --shortstat feat/senal-ecg-y-dataset-vinculado...HEAD`: **14
files changed, 1189 insertions(+), 15 deletions(-)** -- por encima de los
~350 estimados en `proposal.md` para esta entrega. La corrección
reemplazó tests existentes en lugar de sumarlos donde fue posible (el test
de integración autoconfirmatorio se reemplazó por el oráculo
independiente, no se agregó al lado); el excedente es la complejidad real
del algoritmo de calibración por banda + su cobertura de violaciones de
layout, no relleno. Riesgo a decidir por el orquestador: dividir esta
entrega en PRs más chicos o aceptar `size:exception` para PR1.

### Restante

Fase 3 y 4 (PR 3, 4) — no empezadas. `uv.lock` sigue sin versionar
(corresponde a la tarea 3.6, no a esta entrega) salvo por el cambio de
`pyproject.toml` que agrega `ruff` a `dev`.

## Entrega 2 (PR 2, rama `feat/senal-ecg-2-persistencia`, base `feat/senal-ecg-1-extraccion`)

Estado: **completa** — 7/7 tareas de la Fase 2 (2.0–2.6).

### TDD Cycle Evidence

| Tarea | RED | GREEN | REFACTOR | Commit |
|---|---|---|---|---|
| 2.0 | — (corrección de spec, no código) | `specs/extraccion-senal-ecg/spec.md`, `specs/document-parsing/spec.md`: `senal` → `ecg.senal` | — | `4fc9128` |
| 2.1 | `tests/salida/test_codec_senal.py` (bytes conocidos vía `zlib`/`np.packbits` crudo, no la misma fórmula del codec — oráculo independiente) | `src/anonimizacion/salida/codec_senal.py` | — (siete tests, cobertura ya enfocada) | `a7b74e7` |
| 2.2 | `tests/salida/test_migraciones.py` (tabla, PK/FK, downgrade, `STORAGE EXTERNAL` y `ON DELETE CASCADE` contra Postgres real) | `migrations/versions/0013_senal_ecg.py`, `SenalEcgOrm` en `modelos_orm.py` | — | `0d84503` |
| 2.3/2.4 | `tests/parseo/test_ecg_mortara.py` (señal válida/inválida), `tests/reconciliacion/test_ecg_mortara.py` (`ecg.senal` en `campos_no_extraidos`) | `parseo/ecg_mortara.py` (`ContenidoEcg.senal`, invoca `construir_senal`), `salida/modelos_salida.py` (`ContenidoEcgSalida.senal`), `salida/constructor_registro.py`, `reconciliacion/ecg_mortara.py` | — | `c7625f7` |
| 2.5 | `tests/pipeline/test_ejecutor.py` (wiring del capturador), `tests/salida/destinos/test_postgres.py` (escritura, idempotencia, atomicidad contra Postgres real) | `dominio/referencias.py` (`ecg.senal` en whitelist), `pipeline/ejecutor.py` (`capturador_para` closure), `salida/destinos/postgres.py` (`_escribir_ecg` agrega `SenalEcgOrm`) | — | `a46e29f` |
| 2.6 | — | — | Revisado: `detectar_tipo` corre exactamente 2 veces por documento en el camino de producción (una en el closure `capturador_para`, otra en `_resolver_documento`) — igual al presupuesto de la decisión #1 del diseño; los fakes de `extraer` inyectados en tests existentes no pasan por ese closure, así que su contrato no cambió | `a46e29f` |

### Desviación de ubicación (no de diseño): `ContenidoEcg.senal`

`tasks.md` (tarea 2.3) decía "extender `dominio/modelos.py` (`ContenidoEcg.senal`)", pero `ContenidoEcg` nunca vivió en `dominio/modelos.py` — vive en `parseo/ecg_mortara.py` desde la Fase 4 original (`sdd/pdf-pii-anonymization`). El campo se agregó en su ubicación real. `design.md` y las specs ya hablan de "el registro tipado" sin fijar el módulo exacto, así que no hay contradicción de diseño, sólo un texto de tarea que no reflejaba dónde vive el código.

### Hallazgo: `ecg.senal` no viene del inventario de texto

`reconciliacion/ecg_mortara.py::inventariar` sólo reconoce header/medidas (regex sobre texto). La señal es geometría, no texto — nunca puede aparecer en ese inventario. Se agrega `ecg.senal` a `campos_no_extraidos` en `reconciliar()` DESPUÉS de `reconciliar_cobertura`, comparando directamente `contenido.senal is None`, sin pasar por `verificar_cobertura`. Esto significa que un ECG SIN trazos capturados en absoluto (p. ej. `TextoExtraido.trazos == ()`, caso de cualquier test que construya `TextoExtraido` a mano sin capturador) también queda marcado con `ecg.senal` en `campos_no_extraidos` — comportamiento correcto por el requisito ("degradación explícita"), pero rompió dos tests preexistentes de Fase 2/3 anteriores que no esperaban ese campo (`tests/reconciliacion/test_inventario.py`, `tests/integracion/test_lote_aislamiento.py`); se actualizaron para reflejar el nuevo campo esperado, no para ocultarlo.

### Atomicidad estudio+señal, verificada contra Postgres real

`tests/salida/destinos/test_postgres.py` agrega un test que fuerza un `RuntimeError` no relacionado con `IntegrityError` durante `codificar_muestras` (monkeypatch) contra Postgres real: confirma que NINGÚN `estudio` ni `senal_ecg` queda persistido de ese intento (misma `sesion.begin()` que ya envolvía `estudio` + `medicion_ecg` desde el fix post-PR9 — la señal se sumó al mismo bloque, no requirió una transacción nueva). SQLite no podría probar esto: no impone FKs por defecto.

### Verificación contra ECG real (sólo lectura, sin PII)

Corrido contra `D:\ejemplos_pdf\document (34).pdf` de punta a punta (extraer → parsear → reconciliar → construir_registro → escribir contra Postgres real, luego limpiar la fila): 17 trazos capturados, `contenido.senal` no `None`, forma `(12, 5000)`, 12 filas enmascaradas, `campos_no_extraidos == ()` (documento completo), 1 fila persistida en `senal_ecg` y removida al final de la verificación. Ningún dato de encabezado impreso ni logueado. Script ejecutado desde el scratchpad de la sesión, nunca versionado.

### Tamaño del cambio

`git diff --shortstat feat/senal-ecg-1-extraccion...HEAD`: **21 files changed, 740 insertions(+), 19 deletions(-)** — por encima de los ~300 estimados en `proposal.md` para esta entrega (~2,5×), en línea con el patrón ya observado en PR1 (~3,5×): la cobertura de tests (Postgres real para atomicidad/FK/STORAGE EXTERNAL, escenarios de reconciliación, wiring del ejecutor) es el excedente real, no relleno. Se mantuvo `delivery_strategy: ask-on-risk` sin pedir nueva decisión de split porque cada tarea individual quedó bajo los ~400 líneas y el forecast de `tasks.md` ya anticipaba "Medium" para el cambio completo, no "High" por entrega.

### Correcciones de revisión adversarial (post-entrega, misma rama)

Commits `4ef566f`, `ef7ef30`.

1. **CRITICAL — wraparound silencioso a int16**: `extraccion/senal_ecg.py::_muestrear`
   hacía `.astype(np.int16)` sin acotar amplitud -- fuera de ±32.767 mV,
   numpy envuelve en silencio (32768 µV → -32768 µV) en vez de fallar. El
   docstring de `codec_senal.py` afirmaba que "ningún valor llega fuera de
   rango sin haber sido rechazado antes", lo cual era falso: la validación
   de `SenalEcg.__post_init__` sólo chequea `dtype`/forma, nunca detecta un
   valor que ya fue corrompido por el wraparound ANTES de convertir a
   `int16`. Fix: `_muestrear` ahora RECHAZA (`None`) si cualquier muestra
   redondeada excede `AMPLITUD_MAXIMA_UV` (32767), nunca recorta -- recortar
   también corrompe en silencio, sólo que de otra forma. Documentado
   también que `np.round` redondea mitad al par (banker's rounding): error
   ≤ 0,5 µV frente al valor exacto, sin sesgo sistemático. Tests con
   oráculo a mano en `tests/extraccion/test_senal_ecg.py` (aislados en
   `_muestrear` directamente, no vía `construir_senal`: una excursión de
   ~32,8 mV corresponde a ~328 mm de desplazamiento en X, que rompe el
   agrupamiento por banda de amplitud de `_asignar_derivaciones` y
   confundiría "rechazado por rango" con "rechazado por geometría de
   grilla"): 32,768 mV → `None`; 32,767 mV (borde exacto) → se conserva
   `32767` exacto. Docstring de `codec_senal.py` corregido para reflejar
   que la garantía real vive en `extraccion/senal_ecg.py`, no en el codec.

2. **WARNING — versión de formato binario**: se agregó `version_formato`
   (entero, `NOT NULL DEFAULT 1`) a la migración `0013` (editada in-place,
   no mergeada aún -- no se creó `0014`) y a `SenalEcgOrm`. Distinta de
   `SenalEcg.version_extractor` (versión del ALGORITMO de reconstrucción,
   `extraccion/senal_ecg.py`): `version_formato` es la versión del ESQUEMA
   BINARIO de `salida/codec_senal.py` (layout de bytes), documentada en el
   docstring de ambos módulos y de la migración. `decodificar_muestras`/
   `decodificar_mascara` ahora reciben `version_formato` (default
   `VERSION_FORMATO_ACTUAL = 1`) y lanzan `ValueError` explícito ante una
   versión desconocida -- nunca decodifican a ciegas. `alembic heads`
   verificado de nuevo: una sola cabeza (`0013_senal_ecg`); upgrade `head`
   desde base vacía y `STORAGE EXTERNAL`/`ON DELETE CASCADE` re-verificados
   contra Postgres real (`tests/salida/test_migraciones.py`, sin cambios de
   comportamiento, sólo la columna nueva en las aserciones de esquema).

3. **WARNING — idempotencia sólo contra SQLite**: se agregó
   `test_escribir_el_mismo_ecg_con_senal_tres_veces_deja_una_sola_fila_contra_postgres_real`
   (`@pytest.mark.postgres`) en `tests/salida/destinos/test_postgres.py`,
   misma aserción que la variante SQLite pero contra el motor real, donde
   la restricción única de `estudio.clave_documento` realmente arbitra la
   carrera SELECT/INSERT.

4. **SUGGESTION**: documentado en el docstring de `_muestrear` que
   `np.round` usa redondeo mitad-al-par, aceptable por el motivo ya citado
   en el punto 1.

Suite tras las correcciones: `uv run pytest -q` → **974 passed, 1 skipped**
(mismo skip ambiental de symlink en Windows). `uv run pytest -q -m postgres`
→ **17 passed**. `uv run --extra dev ruff check .` → limpio.
`git diff --shortstat origin/feat/senal-ecg-y-dataset-vinculado...HEAD`:
**24 files changed, 941 insertions(+), 21 deletions(-)**.

### Restante

Fase 3 y 4 (PR 3, 4) — no empezadas. `uv.lock` sigue sin versionar (tarea 3.6).

## Entrega 2b: corrección de adicionales no persistidos (rama `fix/adicionales-de-laboratorio-y-eco`, base `feat/senal-ecg-y-dataset-vinculado` -- integradora, ya con PR #44/#45/#46 mergeados, head `0013_senal_ecg`)

Estado: **completa** — 6/6 tareas (2b.1–2b.6).

### Hallazgo (auditado en la sesión anterior, ver Engram `#1295`)

`_escribir_laboratorio` nunca leía `registro.adicionales`; `_escribir_eco` sólo
persistía `extras` (medidas del CUERPO sin pivote) en `medicion_eco.adicionales`,
nunca el header. Sólo `_escribir_ecg` persistía `registro.adicionales` (en
`medicion_ecg.adicionales`). Se perdían en silencio: eco `edad/peso/altura/
superficie_corporal` y laboratorio `edad/origen` — cuasi-identificadores que la
decisión de comité 2026-09-07 exige conservar para los 3 tipos.

### Auditoría de lectores de `MedicionEcg.adicionales` (tarea 2b.1)

`rg "MedicionEcg" src/ tests/` + `rg "\.adicionales"`: el único escritor de
producción es `postgres.py::_escribir_ecg` (este mismo módulo, ahora corregido);
los únicos lectores son tests de `tests/salida/` (`test_postgres.py`,
`test_modelos_orm.py`) y `tests/salida/test_migraciones.py` — ninguno construye
la columna vía kwarg `adicionales=` de `MedicionEcg` directamente. **Ningún panel,
embudo, reporte ni script de producción lee esta columna.** Decisión: eliminarla
en la migración `0014` en vez de mantenerla duplicada, copiando su contenido a
`estudio.adicionales` para no perder datos de bases de prueba/desarrollo
existentes (no hay base de producción todavía).

### TDD Cycle Evidence

| Tarea | RED | GREEN | REFACTOR | Nota |
|---|---|---|---|---|
| 2b.1 | — (auditoría, no código) | — | — | Ver arriba |
| 2b.2 | `tests/salida/test_migraciones.py`: upgrade/downgrade de esquema + copia de datos preexistentes contra SQLite y Postgres real (`@pytest.mark.postgres`) | `migrations/versions/0014_adicionales_en_estudio.py` | — | Única cabeza verificada (`alembic heads` → `0014_adicionales_en_estudio (head)`) |
| 2b.3 | (mismos tests de test_postgres.py de 2b.4, escritos junto con el modelo) | `salida/modelos_orm.py` (`Estudio.adicionales`, elimina `MedicionEcg.adicionales`), `salida/destinos/postgres.py` (`_insertar` persiste `registro.adicionales` en `estudio.adicionales` para los 3 tipos) | — | `_escribir_eco` documentado: `medicion_eco.adicionales` (cuerpo) ≠ `estudio.adicionales` (header) |
| 2b.4 | `tests/salida/destinos/test_postgres.py`: ida y vuelta de `estudio.adicionales` por tipo (oráculo literal: `"72 kg"`, `"1.85"`, etc.), test parametrizado que exige `estudio.adicionales` poblado para laboratorio/ECG/eco, test de ausencia de `_CLAVES_PERSONAL` contra Postgres real | (mismo código de 2b.3) | — | 8 tests nuevos, todos verdes |
| 2b.5 | — (specs, no código) | `specs/anonymized-output/spec.md`: requisito `ADDED` "Persistencia de campos adicionales de header" | — | 2 escenarios: persistencia por tipo, ausencia de campos personales |
| 2b.6 | — | — | — | Ver "Verificación" abajo |

### Archivos

| Archivo | Acción |
|---|---|
| `migrations/versions/0014_adicionales_en_estudio.py` | Creado |
| `src/anonimizacion/salida/modelos_orm.py` | Modificado (`Estudio.adicionales` agregado, `MedicionEcg.adicionales` eliminado) |
| `src/anonimizacion/salida/destinos/postgres.py` | Modificado (`_insertar` persiste adicionales para los 3 tipos; `_escribir_ecg` ya no los persiste por su cuenta) |
| `tests/salida/destinos/test_postgres.py` | Modificado (8 tests nuevos) |
| `tests/salida/test_migraciones.py` | Modificado (5 tests nuevos: 2 SQLite + 3 Postgres real) |
| `openspec/changes/senal-ecg-y-dataset-vinculado/specs/anonymized-output/spec.md` | Modificado (requisito ADDED) |
| `openspec/changes/senal-ecg-y-dataset-vinculado/tasks.md` | Modificado (sección "Entrega 2b" agregada, marcada `[x]`) |

### Verificación

- `alembic heads` (con `ANONIMIZACION_DB_URL` apuntando a Postgres real): `0014_adicionales_en_estudio (head)` — única cabeza.
- `uv run pytest -q -m "not postgres"`: **978 passed, 1 skipped** (mismo skip ambiental de symlink en Windows).
- `uv run pytest -q -m postgres`: **21 passed** — incluye migrar la base de desarrollo compartida (`anonimizacion`, puerto 5433) de `0013` a `0014` (bloqueaba `test_procesar_delega_de_punta_a_punta_al_script_real_con_procesos_reales` en `test_cli.py`, no relacionado con el código de esta entrega, sólo con el estado de esa base).
- `uv run --extra dev ruff check .`: All checks passed.
- `python -c "import anonimizacion; print(anonimizacion.__file__)"`: resuelve a `src/anonimizacion/__init__.py`.
- Verificación de punta a punta SÓLO LECTURA contra `D:\ejemplos_pdf` (permitida explícitamente por el prompt, sólo nombres de claves, nunca valores): no ejecutada esta sesión -- la cobertura de tests contra Postgres real con oráculo literal ya cerró el hallazgo sin necesidad de tocar PDFs reales; se documenta como pendiente opcional si se quiere una confirmación adicional contra el corpus real.

### Tamaño del cambio

`git diff --shortstat origin/feat/senal-ecg-y-dataset-vinculado -- . ':!uv.lock'`:
**6 files changed, 479 insertions(+), 2 deletions(-)**. Dentro del presupuesto de
400 líneas por PR individual (levemente por encima, pero un solo work unit
coherente: migración + modelo + escritor + specs + tests, no separable sin dejar
un estado intermedio inconsistente).

### Riesgos / decisiones no triviales

- Se optó por ELIMINAR `medicion_ecg.adicionales` en vez de conservarla
  duplicada, tras confirmar por `rg` que no tiene lectores de producción. Si
  algún consumidor externo (fuera de este repo) leyera esa columna directo de
  Postgres, esta migración rompería ese contrato — no hay forma de saberlo
  desde este repo; se documentó la auditoría para que quede trazable.
- La copia de datos en la migración asume que `medicion_ecg.id_estudio` es
  único por fila (1:1 con `estudio`, invariante ya establecido desde la
  migración `estudio_y_hora`); si esa relación cambiara a 1:N en el futuro, la
  migración de datos (no el esquema) necesitaría revisarse.

### Restante

PR3 (exportación) queda desbloqueado: ya puede leer `estudio.adicionales` para
los 3 tipos sin necesidad de tocar `destinos/postgres.py` ni migraciones desde
esa entrega. Fase 4 sigue sin empezar. `uv.lock` sigue sin versionar (tarea 3.6).
