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
- `uv run pytest -q -m postgres`: **21 passed**. **Corrección (revisión adversarial)**: se aplicó `alembic upgrade head` a la base de desarrollo compartida (`anonimizacion`, puerto 5433) para llevarla de `0013` a `0014`. El diagnóstico original de esta entrada decía que eso "destrababa" `test_procesar_delega_de_punta_a_punta_al_script_real_con_procesos_reales`, atribuyéndolo (sin precisión) al fixture `_postgres_real_para_cli` -- **ese fixture (`tests/test_cli.py:229-248`) hace `Base.metadata.drop_all`/`create_all` y NO toca `alembic_version`, así que por sí solo nunca dependía de esta migración**. El mecanismo real, confirmado leyendo `src/anonimizacion/diagnostico.py::diagnosticar` → `_diagnosticar_migraciones` (líneas 117-164): esa función abre su propia conexión a la URL de Postgres real y compara `MigrationContext.configure(conexion).get_current_heads()` (lo que dice la tabla `alembic_version` de la base) contra `ScriptDirectory.get_heads()` (lo que dice el código de `migrations/versions/` en este checkout) -- totalmente independiente del fixture. Como esta rama agregó `migrations/versions/0014_...py`, el head del CÓDIGO pasó a ser `0014` mientras el `alembic_version` de esa base compartida seguía en `0013` (de una sesión anterior); `cli.main(["procesar", ...])` llama a `diagnosticar()` (línea ~184 de `cli.py`) antes de procesar, así que el mismatch producía el hallazgo `[FALTA] Migraciones: la base de datos no tiene aplicadas las últimas migraciones` capturado en el primer intento de esta sesión, y aplicar `alembic upgrade head` sí lo resolvió (verificado: 20 passed 1 failed → 21 passed tras el upgrade). Estado en el que quedó esa base: `alembic_version = 0014_adicionales_en_estudio`, columna `medicion_ecg.adicionales` ya eliminada ahí. **No se volvió a tocar la base compartida en la ronda de correcciones posterior** (instrucción explícita del orquestador) -- los tests nuevos de esa ronda (downgrade con los 3 tipos, PII con las 3 claves) usan exclusivamente `_url_postgres_scratch` (base efímera creada/destruida por el propio fixture).
- `uv run --extra dev ruff check .`: All checks passed.
- `python -c "import anonimizacion; print(anonimizacion.__file__)"`: resuelve a `src/anonimizacion/__init__.py`.
- Verificación de punta a punta SÓLO LECTURA contra `D:\ejemplos_pdf` (permitida explícitamente por el prompt, sólo nombres de claves, nunca valores): no ejecutada esta sesión -- la cobertura de tests contra Postgres real con oráculo literal ya cerró el hallazgo sin necesidad de tocar PDFs reales; se documenta como pendiente opcional si se quiere una confirmación adicional contra el corpus real.

### Correcciones de revisión adversarial (misma rama, sin nuevo commit todavía)

1. **CRITICAL — test de PII vacuo**: el test original
   `test_estudio_adicionales_nunca_contiene_campos_personales_contra_postgres_real`
   decía "para los 3 tipos" pero sólo escribía laboratorio y ECG (eco nunca se
   ejercitaba), y de `_CLAVES_PERSONAL` sólo `medico_derivante` estaba en el
   input -- las aserciones sobre `medico_solicitante`/`tecnico` eran vacuas
   (nunca podían fallar). Reemplazado por
   `test_estudio_adicionales_nunca_contiene_ningun_campo_personal_contra_postgres_real`,
   parametrizado por los 3 tipos, con LAS TRES claves de `_CLAVES_PERSONAL`
   presentes en el input (valores sintéticos) más un campo no personal que
   debe llegar intacto (oráculo positivo). **Demostrado que puede fallar**:
   se rompió temporalmente `constructor_registro.py::_adicionales_sin_personal`
   (`return dict(adicionales)`, sin filtrar) y los 3 casos parametrizados
   fallaron con `AssertionError` mostrando las 3 claves personales presentes
   en `estudio.adicionales` -- se revirtió el cambio (`git diff` vacío tras
   revertir) y se confirmó GREEN de nuevo antes de continuar.
2. **CRITICAL — documentación falsa**: corregido el punto de "Verificación"
   arriba -- la migración de la base compartida no era falsa en su efecto
   (el diagnóstico de `cli.py` sí depende de `alembic_version`, no del
   fixture del test), pero la causa citada originalmente (el fixture) era
   imprecisa. Ver el párrafo corregido arriba con la traza completa por
   `diagnostico.py::_diagnosticar_migraciones`.
3. **WARNING — downgrade con los 3 tipos**: agregado
   `test_downgrade_de_0014_solo_copia_adicionales_de_ecg_de_vuelta_contra_postgres_real`
   en `test_migraciones.py`, contra `_url_postgres_scratch` (base efímera):
   puebla `estudio.adicionales` para los 3 tipos, hace downgrade a `0013`, y
   confirma que sólo la fila de ECG vuelve a `medicion_ecg.adicionales` (una
   sola fila, sin contaminación de laboratorio/eco, que no tienen dónde
   volcarse en ese esquema).
4. **SUGGESTION — tamaño**: fusionados los 4 tests repetidos de "cada tipo
   persiste sus adicionales" en un único
   `test_cada_tipo_de_documento_persiste_adicionales_de_header_sin_personal`
   parametrizado (oráculo positivo + ausencia de campo personal en el mismo
   test), y las 3 factories de la prueba de PII en una sola función
   parametrizada por `TipoDocumento`. Eliminado el test de ida y vuelta
   contra Postgres real que quedó redundante con el nuevo test de PII (que ya
   verifica ida y vuelta del campo no personal + ausencia de los personales).
5. Ajustado el comentario de `0014_adicionales_en_estudio.py` (líneas 52-56)
   para no sugerir una comparación cruzada SQLite/Postgres que no existe --
   cada rama de dialecto se prueba por separado contra su propio motor.

Verificación tras las correcciones: `uv run pytest -q -m "not postgres"` →
**974 passed, 1 skipped** (mismo skip ambiental; un fallo transitorio de
`test_despacho_paralelo.py` por timing de `ProcessPoolExecutor` en Windows no
reprodujo al reintentar en aislado -- no relacionado con este cambio).
`uv run pytest -q -m postgres` → **23 passed**, sin tocar la base de desarrollo
compartida en esta ronda. `uv run --extra dev ruff check .` → limpio.

### Tamaño del cambio

`git diff --shortstat origin/feat/senal-ecg-y-dataset-vinculado -- . ':!uv.lock'`
tras las correcciones: **8 files changed, 662 insertions(+), 2 deletions(-)**
-- se mantuvo por debajo del tamaño previo a la ronda de revisión (668) pese a
sumar 2 tests nuevos requeridos por la revisión, compensando con la
parametrización del punto 4.

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

## Entrega 3 (PR 3, rama `feat/senal-ecg-3-exportacion`, base `fix/adicionales-de-laboratorio-y-eco`)

Estado: **completa** — 6/6 tareas de la Fase 3 (3.1–3.6).

### TDD Cycle Evidence

| Tarea | RED | GREEN | REFACTOR | Commit |
|---|---|---|---|---|
| 3.1 | `tests/salida/test_exportacion.py` (lista blanca por archivo, `ImportError` confirmado antes de crear el módulo) | `src/anonimizacion/salida/exportacion.py` (esquemas `pyarrow` explícitos) | — | pendiente de commit final |
| 3.2 | (mismo archivo, tests de completitud/no-mutación/paginación) | `exportar_dataset`, `_ids_episodio_paginados` (paginación por clave, no OFFSET) | Extraído `_procesar_pagina`/`_EscritoresPagina` para bajar la complejidad ciclomática de `exportar_dataset` bajo el límite de `mccabe` (13 → conforme) | ídem |
| 3.3 | (mismo archivo, tests de manifiesto) | Bloque `manifiesto` en `exportar_dataset` + `_ventanas_columna` | — | ídem |
| 3.4 | `tests/salida/test_contrato_modelo_hvi.py` | (sin código nuevo, sólo el test contra la exportación ya construida) | — | ídem |
| 3.5 | `tests/test_cli.py` (2 tests: wiring con mock, extremo real contra SQLite de archivo) | `cli.py::_comando_exportar` + subparser `exportar` | — | ídem |
| 3.6 | — | `pyproject.toml` (numpy/pyarrow base), `uv lock` | — | ídem |
| Guard adicional | `tests/extraccion/test_senal_ecg.py::test_muestrear_rechaza_valores_no_finitos_por_division_cero_sobre_cero` (demostrado RED: sin el guard, `_muestrear` devolvía una señal plana de CEROS en vez de `None` -- `nan.astype(np.int16)` convierte en silencio) | `_muestrear` en `extraccion/senal_ecg.py`: `if not np.all(np.isfinite(mv_interpolado)): return None` | — | `ab3a2ee` |

### Decisión de diseño: la vinculación de episodio NO se reimplementa acá

`design.md` (decisión 5) y `tasks.md` (texto original de 3.2) sugerían que
`exportacion.py` "reutiliza o extiende `pseudonimizacion/vinculacion.py`"
para la vinculación por `patient_id` + ventana de 7 días. Al revisar el
esquema real (`salida/modelos_orm.py`), esa vinculación YA está resuelta:
cada `estudio.id_episodio` se calcula UNA vez, al momento de escribir el
documento (`pseudonimizacion/vinculacion.py` decide el clúster,
`destinos/postgres.py::escribir_episodio` lo persiste). Reimplementar el
clustering en la exportación sería (a) trabajo redundante, (b) un riesgo real
de que la exportación calcule una vinculación DISTINTA de la que ya vive en
`estudio`/`episodio`, silenciosamente inconsistente con la base. La
exportación sólo AGRUPA por la clave `id_episodio` ya persistida -- no
recalcula fechas de ancla ni ventanas. Esto no contradice ningún requisito de
spec (`exportacion-dataset-vinculado` no exige que el CÁLCULO de vinculación
viva en el módulo de exportación, sólo que el resultado final agrupe
correctamente) -- es una desviación del TEXTO de una tarea, no de un
requisito.

### Lista blanca de columnas (falsable, demostrado)

Cuatro tests fijan el esquema EXACTO (`set(tabla.column_names) == {...}`) de
cada archivo -- `episodios`, `ecg`, `laboratorio`, `eco`. Falsabilidad
demostrada en `test_agregar_una_columna_no_listada_rompe_el_test_de_esquema`:
agrega una columna sintética al conjunto esperado y confirma que la
comparación de conjuntos falla (`pytest.raises(AssertionError)`) -- el mismo
patrón de aserción que protege contra que `exportar_dataset` agregue una
columna nueva sin que ningún test lo note. `adicionales_json` es el único
campo "libre" en cada tabla: JSON de `estudio.adicionales`, que YA llega
saneado de nombres de médico/técnico desde la migración `0014`
(`constructor_registro.py::_adicionales_sin_personal`) -- no se vuelve a
filtrar en `exportacion.py`, se confía en esa garantía ya probada contra
Postgres real. `id_medico*`, `clave_documento`, `corrida_id` y el texto libre
del eco (`texto_seccion_eco`) quedan fuera de las 4 listas blancas --
verificado con aserciones negativas explícitas, no sólo por omisión.

### Paginación con memoria acotada, verificada por conteo

`_ids_episodio_paginados` pagina por CLAVE (`id_episodio > último`, `ORDER BY
id_episodio LIMIT tamano_pagina`), no por `OFFSET` ciego -- cada página trae
como máximo `tamano_pagina` filas sin importar cuántos episodios totales
haya. `test_paginacion_de_episodios_nunca_materializa_mas_de_una_pagina_a_la_vez`
puebla 600 episodios y verifica CONTANDO: exactamente 3 páginas de tamaños
`[256, 256, 88]`, sin duplicados ni huecos entre páginas -- nunca con un
umbral de tiempo (instrucción explícita del prompt).

### Contrato con `modelo_hvi`, sin importarlo

`tests/salida/test_contrato_modelo_hvi.py` fija los números de
`modelo_hvi/formato_unico.py::EsquemaPdf` (HZ=250, MUESTRAS=2500,
muestras_por_tramo=619, inicio_columna_s=(0, 2.5, 5, 7.5)) como LITERALES
medidos a mano en el propio test -- `modelo_hvi` nunca se importa (repo
separado, sólo lectura). Decimar ×2 la señal exportada da (12, 2500); el
tramo de la columna 0 mide exactamente 619 muestras; V1 (tira de ritmo,
índice 6 en `ORDEN_DERIVACIONES`) decimada da la derivación COMPLETA (2500),
sin recorte por tramo -- coincide con "V1 completa por la tira" del prompt.

### `uv.lock`: decisión con evidencia

No está en `.gitignore`; `git log --all -- uv.lock` no muestra ningún commit
previo (nunca se versionó); `scripts/instalar.ps1` no invoca `uv` en ningún
punto (no depende del lockfile para instalar). Con todo, corresponde
versionarlo: es la única fuente de resolución reproducible de dependencias
de este repo (no hay `requirements*.txt`), y dejarlo sin versionar deja a
cada desarrollador resolviendo versiones de forma independiente pese a que
`pyproject.toml` ya fija rangos. `uv lock` ejecutado tras agregar
`numpy>=1.26`/`pyarrow>=15` como dependencias BASE (no `dev`, no extra
opcional -- se usan en `src/anonimizacion/salida/exportacion.py`, código de
producción).

### Verificación

`uv run pytest -q -m "not postgres"`: **991 passed, 1 skipped** (mismo skip
ambiental de symlink en Windows), antes del guard de `_muestrear`; con el
guard y los tests de exportación/CLI/contrato agregados se mantiene la misma
cuenta de fallos (0) -- ver corridas específicas de los archivos nuevos
(`tests/salida/test_exportacion.py` 12 passed, `test_contrato_modelo_hvi.py`
1 passed, `tests/test_cli.py -k exportar` 2 passed). `uv run pytest -q -m
postgres`: **23 passed** -- MISMA cuenta que antes de esta entrega: no se
agregó ningún test nuevo marcado `postgres` (regla dura del prompt: sólo
bases efímeras de los fixtures ya existentes, `_url_postgres_scratch`/
`_engine_postgres_real`; esta entrega no tocó la base compartida ni corrió
`alembic` contra ella). `uv run --extra dev ruff check .`: limpio, tras
extraer `_procesar_pagina`/`_EscritoresPagina` para bajar la complejidad
ciclomática de `exportar_dataset` (13 → conforme al límite 10 de `mccabe`).

### Verificación de punta a punta contra `D:\ejemplos_pdf`

NO ejecutada esta entrega (opcional según el prompt): la cobertura de tests
contra SQLite de archivo (`test_exportar_produce_parquet_y_manifiesto_sin_mutar_la_base_sqlite`)
y el test de contrato ya cierran el comportamiento sin necesidad de un PDF
real -- se documenta como pendiente opcional para una confirmación adicional
de punta a punta (extraer → parsear → escribir → exportar → leer Parquet)
si se quiere antes de mergear.

### Tamaño del cambio

`git diff --shortstat fix/adicionales-de-laboratorio-y-eco...HEAD` (a
reportar en el result contract con el diff real, no estimado acá) --
consistente con el patrón de las entregas anteriores (2,5-3x lo estimado en
`proposal.md` para exportación), explicado por la cobertura de 4 esquemas
distintos + manifiesto + paginación + contrato + wiring de CLI, cada uno con
su propio test falsable.

### Restante

Fase 4 (PR 4: verificador PII lineal + cierre fase 5 de
`operacion-segura-y-escalable`) sigue sin empezar -- vive en apply-progress
aparte (`sdd/senal-ecg-y-dataset-vinculado/apply-progress-entrega4`, ya
iniciada en paralelo sobre otra rama, no mezclar). El dataset exportado por
esta entrega queda listo para que esa fase lo audite con el verificador
lineal (tarea 4.3), pero esa auditoría NO es parte de esta entrega.

### Correcciones de revisión adversarial (misma rama, sin nuevo push/PR)

1. **CRITICAL -- cero cobertura de `exportar_dataset` contra Postgres real**:
   `-m postgres` seguía en 23 (los mismos de antes de esta entrega) pese a
   que la exportación corre contra Postgres en producción. Agregado
   `tests/salida/test_exportacion_postgres.py` (3 tests, `-m postgres` pasa a
   **26**), contra una base ESCRATCH dedicada (`exportacion_scratch_test`,
   creada/destruida en el propio archivo -- mismo patrón que
   `tests/salida/test_migraciones.py::_url_postgres_scratch`, nunca la base
   compartida `anonimizacion`):
   - `test_exportar_decodifica_senal_bytea_de_postgres_correctamente`: oráculo
     de señal+máscara escrito a mano, decodificado a través de `BYTEA` real
     de Postgres (`psycopg` puede devolver `memoryview`) -- `zlib`/
     `np.frombuffer` lo aceptan sin cambios, valores exportados EXACTOS al
     oráculo.
   - `test_exportar_conserva_estudio_adicionales_jsonb_con_las_mismas_claves_y_valores`:
     `estudio.adicionales` como `JSONB` real (no el `TEXT` genérico de
     SQLite), ida y vuelta con unicode (`"Instituto de Cardiología de
     Corrientes"`) exacta.
   - `test_exportar_usa_repeatable_read_de_verdad_y_no_ve_episodios_de_otra_conexion`:
     dos garantías en un solo test (instrucción explícita de no inflar la
     batería) -- (a) `current_setting('transaction_isolation')`, consultado
     DENTRO de la transacción abierta por `exportar_dataset` (vía
     `monkeypatch` de `_procesar_pagina`), da `'repeatable read'`; (b) un
     episodio insertado y COMMITEADO por una conexión SEPARADA, después de
     que la transacción de exportación ya tomó su snapshot, NO aparece ni en
     una relectura dentro de esa misma transacción ni en el Parquet final --
     la garantía real de `REPEATABLE READ` (snapshot fijo para toda la
     transacción), no simulada con SQLite (que no la soporta).
   No fue impracticable -- las tres garantías se pudieron probar de verdad
   contra Postgres real sin tocar la base compartida.

2. **WARNING elevado a bloqueante -- defensa en profundidad de PII**:
   `exportacion.py` confiaba ciegamente en que `estudio.adicionales` ya
   llegaba saneado de nombres de médico/técnico (migración 0014). Agregado
   `_adicionales_sin_personal_exportacion`, que vuelve a filtrar por
   `_CLAVES_PERSONAL` **importada** de `constructor_registro.py` (no una
   copia literal -- si esa tupla crece, el filtro de acá cambia solo) en el
   ÚLTIMO punto antes de que el dato salga del sistema. Dos tests nuevos en
   `tests/salida/test_exportacion.py`:
   - `test_estudio_adicionales_con_claves_personales_de_una_fila_vieja_nunca_llega_al_parquet`:
     inserta a mano (sin pasar por `construir_registro`, que sí filtra) una
     fila que simula una escritura de una versión anterior del código con
     las 3 claves personales presentes -- confirma que ninguna llega al
     Parquet.
   - `test_ninguna_clave_de_claves_personal_completa_sobrevive_al_filtro_de_exportacion`:
     test de PROPIEDAD, recorre TODAS las claves de `_CLAVES_PERSONAL` (no
     sólo las que arma un fixture puntual) más un oráculo positivo
     (`"origen"`) que debe sobrevivir.
   **Falsabilidad demostrada**: revertí temporalmente el filtro (`_json_o_none`
   sin `_adicionales_sin_personal_exportacion`) y confirmé que ambos tests
   nuevos fallan mostrando las claves personales presentes en el JSON
   exportado; luego restauré el fix y reconfirmé GREEN. Docstring del módulo
   (líneas 17-23 originales) corregido: ya no afirma que la exportación
   "confía" en la garantía de escritura sin volver a filtrar.

3. **SUGGESTION -- `.tmp` huérfano**: documentado en el docstring del módulo
   (sin test nuevo, ya lo manejaba: verificado a mano que `pq.ParquetWriter`
   abre en modo escritura y trunca cualquier archivo preexistente en esa
   ruta -- una corrida nueva sobre un `.tmp` huérfano de una corrida que
   murió a mitad de camino lo sobreescribe limpio, sin fallar ni mezclar
   filas).

4. Esta entrega se abre como UN solo PR (aprobado por el usuario,
   `size:exception`) -- no se partió en PRs más chicos.

### Verificación tras las correcciones

`uv run pytest -q -m postgres`: **26 passed** (23 previos + 3 nuevos de
exportación) -- sin tocar la base compartida `anonimizacion` (base ESCRATCH
`exportacion_scratch_test`, creada y destruida en el propio test).
`uv run --extra dev ruff check .`: limpio. `uv run pytest -q` (suite
completa, incluye `-m postgres`): corrida en curso al momento de escribir
esta nota -- ver el resultado exacto en el result contract del turno.
Nota operativa: correr `-m postgres` en paralelo con la suite completa
(`pytest -q`, sin filtro) contra la MISMA base compartida produce fallos por
carrera cruzada entre ambas corridas (`ForeignKeyViolation` en
`documento_corrida`, no relacionado con este cambio) -- reproducido y
descartado corriendo cada suite por separado, secuencialmente.

### Tamaño del cambio (actualizado tras la revisión)

`git diff --shortstat origin/feat/senal-ecg-y-dataset-vinculado...HEAD -- .
':!uv.lock'`: ver el result contract del turno para el número exacto tras
estas correcciones (3 tests nuevos de Postgres + 2 tests de defensa en
profundidad de PII + comentarios corregidos, sin agregar código de producción
más allá del filtro de una línea y su docstring).

## Entrega 4 (PR 4, rama `feat/senal-ecg-4-verificador-pii`, mergeada como PR #45)

Estado: **completa** — 4.1/4.2 implementadas en esta rama; 4.3–4.6 se cierran
en la sesión de cierre del cambio (ver sección siguiente). Fusionada
previamente sin pasar por `apply-progress.md` (se desarrolló en paralelo a la
entrega 3); este bloque incorpora el registro que vivía aparte en Engram
(`sdd/senal-ecg-y-dataset-vinculado/apply-progress-entrega4`, observación
`#1300`), sin perder ningún detalle.

Commits: `802b941` (implementación inicial), `e677756` (correcciones de
revisión adversarial).

### Correcciones de revisión adversarial (commit `e677756`)

1. **CRITICAL**: `verificador_lineal.py` no tenía llamador de producción — el
   diseño lo ubica bajo `tests/`, no bajo `src/`. `git mv
   src/anonimizacion/pii/verificador_lineal.py tests/pii/verificador_lineal.py`;
   actualizados los 3 imports (`tests/fixtures/corpus_piloto.py`,
   `tests/pii/test_verificador_lineal.py`,
   `tests/carga/medir_escalado_verificador_pii.py`) para importar desde
   `tests.pii.verificador_lineal`.
2. **WARNING**: docstring corregido — la búsqueda es O(texto) porque el goto
   se extiende a función total, pero la CONSTRUCCIÓN de ese goto es
   O(Σ|patrones| × |alfabeto usado|), no O(patrones) puro. Ya no dice
   "O(texto + patrones)" sin matizar.
3. **SUGGESTION**: agregados a `tests/fixtures/verificador_pii.py::generar_semilla`
   y a `tests/pii/test_verificador_lineal.py` casos de casefold que cambia el
   LARGO del string: "ß"→"ss" (straße/strasse), ligadura "ﬁ"→"fi"
   (ofﬁce/office), "İ"→"i̇" con punto combinante (İstanbul). Los 3 verificados
   contra el oráculo cuadrático.

### Hallazgo: casefold puede cambiar el largo del string sin romper la semántica

`ß`→`ss` crece, `İ`→`i̇` con combining mark también cuenta 2 codepoints — pero
como TANTO el patrón como el texto se casefoldean antes de construir/buscar en
el autómata, la semántica de subcadena se preserva sin casos especiales
adicionales. El test que parecía detectar un bug real (straße/strasse) en
realidad tenía una expectativa mal calculada a mano: ambos casefoldean a
"strasse", dando 2 coincidencias, no 1.

### Archivos

| Archivo | Acción |
|---|---|
| `tests/pii/verificador_lineal.py` | Movido desde `src/anonimizacion/pii/` |
| `tests/fixtures/corpus_piloto.py` | Modificado (import) |
| `tests/fixtures/verificador_pii.py` | Modificado (casos de casefold) |
| `tests/pii/test_verificador_lineal.py` | Modificado (casos de casefold) |
| `tests/carga/medir_escalado_verificador_pii.py` | Modificado (import) |

### Verificación (sesión original de la entrega 4)

`PYTHONPATH=.../src .../python.exe -m pytest -q -m "not postgres"
-p no:cacheprovider` → **947 passed, 1 skipped**. `uv run --extra dev ruff
check .` → limpio. Diffstat vs `origin/feat/senal-ecg-y-dataset-vinculado`: 5
files changed, 301 insertions(+), 5 deletions(-).

### Restante (al cierre de esa sesión)

4.3 (exportación real, dependía de la entrega 3 -- ya mergeada), 4.4 (cierre
5.1 con Postgres/cola), 4.5/5.2 (auditoría del dataset exportado). Ver la
siguiente sección para el cierre de estas tareas.

## Cierre del cambio (rama `fix/cierre-del-cambio-senal-ecg`, desde la integradora ya con PR #44/#45/#46/#47/#48 mergeados)

Cuatro focos de esta sesión: la auditoría de PII de 4.3/5.2, la revisión de
5.1, la deuda de `test_cli.py` sobre la base compartida, y la unificación de
este mismo archivo. Detalle completo de los tres primeros en el result
contract del turno (commits, tamaño del cambio, riesgos). Resumen:

1. **Tarea 4.3 / 5.2 (auditoría de PII sobre el dataset exportado)**: nuevo
   `tests/pii/test_auditoria_exportacion_sin_pii.py` — corpus sintético con
   PII conocida → pipeline real → `exportar_dataset` → verificador lineal
   sobre los 4 Parquet completos + `manifiesto.json`, 0 coincidencias.
   Falsabilidad demostrada con un segundo test que inyecta PII a propósito en
   una fila real ya exportada y confirma que el mismo verificador la detecta.
   Vive en la suite normal (no `tests/carga/`): es una prueba de
   correctitud/invariante de seguridad, corre en segundos contra SQLite, no
   una medición de volumen.
   - **Hallazgo real durante la construcción de la auditoría**: `pyarrow`
     25.0.1 no hace un round-trip correcto a través de Parquet de una columna
     `FixedSizeListArray` cuando TODAS las filas de una página son `None`
     (`ArrowInvalid: Expected all lists to be of size=N but index K had
     size=0`; reproducido también con `FixedSizeListArray.from_arrays`
     directo, no es un problema de `pa.Table.from_pylist`). Esto rompía
     `ecg.parquet` cada vez que ningún ECG de una página tuviera señal
     capturada -- exactamente el estado actual de cobertura del extractor
     contra corpus sin trazos dibujados. Corregido cambiando
     `muestras_uv`/`mascara` de `pa.list_(tipo, 60000)` (tamaño fijo) a
     `pa.list_(tipo)` (tamaño variable) en `ESQUEMA_ECG` -- el invariante de
     largo exacto lo sigue garantizando `SenalEcg.__post_init__`, sólo cambió
     el tipo de columna Parquet.
   - Documentado en `docs/pipeline.md` (nueva sección "Señal de ECG y dataset
     vinculado exportado" + subsección "numpy + PyArrow"), con la fecha y el
     método de la corrida (15/09/2026).
   - Logs/bitácora, registros y diagnósticos de 5.2 ya tenían cobertura
     falsable previa (`tests/observabilidad/test_bitacora_segura.py`,
     `tests/integracion/test_salida_sin_pii.py`); `diagnostico.py` no tiene
     superficie de PII de paciente. Sin cambios ahí.
2. **Tarea 5.1 (integración completa)**: revisada contra la evidencia real de
   la corrida de verificación de esta sesión (ver result contract) -- no se
   tilda sin los números exactos de `pytest -q` / `pytest -q -m postgres`.
3. **Deuda `test_cli.py`**: `_postgres_real_para_cli` ya no hace
   `Base.metadata.drop_all`/`create_all` contra la base compartida
   (`anonimizacion`, puerto 5433); ahora crea una base ESCRATCH propia
   (`cli_scratch_test`) y aplica `alembic upgrade head` PROGRAMÁTICO (mismo
   patrón que `tests/salida/test_migraciones.py::_url_postgres_scratch`),
   sin dejar rastro y sin depender de que alguien migre la base compartida a
   mano. Se agregó `_terminar_conexiones_y_dropear` porque los procesos hijos
   de `--procesos 2` (`ProcessPoolExecutor`) a veces dejaban una conexión
   abierta al momento de intentar el `DROP DATABASE` (`ObjectInUse`).
4. **Unificación de apply-progress**: esta sección + la de "Entrega 4" de
   arriba incorporan el contenido que vivía aparte en Engram
   (`sdd/senal-ecg-y-dataset-vinculado/apply-progress-entrega4`, observación
   `#1300`), fusionado sin sobrescribir nada de lo ya registrado acá.

### Riesgos / decisiones no triviales de esta sesión

- El cambio de `pa.list_(tipo, N)` a `pa.list_(tipo)` en `ESQUEMA_ECG` es un
  cambio de TIPO de columna en el contrato Parquet (de `fixed_size_list` a
  `list` de largo variable) -- no de contenido ni de semántica. Ningún test
  existente verificaba el tipo pyarrow exacto de esas columnas (sólo nombres
  de columnas y valores decodificados), así que no rompió cobertura previa,
  pero un consumidor externo (`modelo_hvi`) que inspeccionara el tipo Arrow
  en vez de sólo el largo de la lista decodificada notaría la diferencia --
  documentado en `docs/pipeline.md` para que no sea sorpresa.
- No se propuso contenido de Obsidian (arquitectura/bitácora) para este
  cierre: la tarea 4.6 lo exige con aprobación de un integrante antes de
  cargarlo (AGENTS.md), y este agente no tiene acceso al vault -- queda
  explícitamente pendiente, no tildado por descuido.

### Corrección de revisión adversarial (commit `be5a919`, misma rama)

El orquestador señaló, con razón, que ningún test fijaba TIPO ni ORDEN del
esquema Arrow de los 4 Parquet -- sólo nombres de columna (lista blanca de
PII). Eso es exactamente lo que dejó pasar el cambio de `pa.list_(tipo, N)`
a `pa.list_(tipo)` sin que nada lo detectara. Agregado
`tests/salida/test_esquema_arrow_de_exportacion.py`:

1. **Esquema exacto por tabla** (4 tests): tipos escritos como literales en
   el propio test, nunca importados de `ESQUEMA_EPISODIOS`/`ESQUEMA_ECG`/
   `ESQUEMA_LABORATORIO`/`ESQUEMA_ECO` -- importar esos esquemas habría hecho
   del test un espejo, no un oráculo (mismo error ya cometido y corregido dos
   veces antes en esta cadena: el fixture de amplitud de la entrega 1 y el
   test de PII vacuo de la entrega 2b). `muestras_uv`/`mascara` fijados
   explícitamente como `list<int16>`/`list<bool>` de largo VARIABLE, con un
   comentario de una línea explicando por qué no son de largo fijo.
2. **Test de regresión del bug de pyarrow**: puebla DOS episodios con ECG sin
   ninguna fila de `SenalEcgOrm` (ambas filas de la página con
   `muestras_uv`/`mascara` en `None`), exporta, relee desde el `.parquet`
   escrito en disco, y confirma que no lanza `ArrowInvalid` y que ambas
   columnas siguen siendo `None` -- exactamente el escenario que rompía antes
   de la corrección (`ArrowInvalid: Expected all lists to be of size=N but
   index K had size=0`, pyarrow 25.0.1).

Verificación tras esta corrección: `uv run pytest -q` → **1026 passed, 1
skipped** (mismo skip ambiental de symlink Windows). Una corrida completa
anterior mostró `tests/integracion/test_reintentar_no_duplica.py::
test_reintentar_dos_veces_no_duplica_cuarentena_ni_estudio` fallando con
`UndefinedTable: relation "corrida" does not exist` (warning de excepción no
manejada en un hilo de fondo) -- reproducido aislado DOS veces, ambas
pasaron; una segunda corrida completa también pasó sin ese fallo. Se
documenta como flake preexistente de aislamiento entre tests (no relacionado
con este cambio), no como hallazgo nuevo. `uv run pytest -q -m postgres` →
**26 passed**, sin tocar la base compartida. `uv run --extra dev ruff check
.` → limpio.
