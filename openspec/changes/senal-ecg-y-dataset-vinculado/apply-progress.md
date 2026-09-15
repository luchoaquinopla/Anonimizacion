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

Ninguna decisión de negocio deviada. Un matiz respecto del texto tentativo
de `design.md` (algoritmo, paso 1): el propio diseño lo marcaba como
"pregunta abierta" a fijar por el test de la tarea 1.1, y el resultado
medido (sin aplicar `derotation_matrix`) reemplaza esa redacción tentativa —
no es una desviación, es la resolución explícita de la ambigüedad que el
diseño delegaba a esta tarea.

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

Fase 2, 3 y 4 (PR 2, 3, 4) — no empezadas. `uv.lock` sigue sin versionar
(corresponde a la tarea 3.6, no a esta entrega) salvo por el cambio de
`pyproject.toml` que agrega `ruff` a `dev`.
