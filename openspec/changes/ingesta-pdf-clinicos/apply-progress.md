# Progreso de aplicación: PR 2 — privacidad y límites operativos

## Estado consumido

- Cambio: `ingesta-pdf-clinicos`; `apply=ready`.
- Contexto de acción: `repo-local`, raíz autorizada `D:\proyectos\anonimizacion`; sin advertencias.
- Alcance aplicado: sólo PR 2. No se inició PR 3/UI, persistencia, calidad habilitable ni otras familias.

## Ciclos TDD

| Ciclo | Evidencia RED | Evidencia GREEN | Evidencia TRIANGULATE / REFACTOR |
| --- | --- | --- | --- |
| Privacidad residual | `tests/test_flujo_privacidad_pr2.py` falló inicialmente: 4 fallos por dependencias no inyectables y excepciones sin convertir. | Se inyectan anonimización y validación; el hallazgo residual y los campos requeridos no verificables devuelven sólo códigos seguros. | Se cubrieron los fallos de extracción y validación aplicables sin lote; TRIANGULATE queda satisfecho sólo para esos casos porque PR 2 no implementa procesamiento por lote. La comprobación de dependencias laterales prohibidas permanece verde. |

## Trabajo completado

- Se añadió una etapa explícita de anonimización antes de la validación residual independiente.
- `PuertoEntradaIngesta` acepta un validador y un anonimizador inyectables, aplica controles de campos obligatorios reales y convierte fallos de extracción o validación en rechazos técnicos seguros.
- Las referencias transitorias se liberan en el flujo de éxito y error; la salida conserva sólo decisión, códigos y conteos.
- Se actualizaron inmediatamente las casillas completadas de RED, GREEN, TRIANGULATE aplicable sin lote, REFACTOR y cierre de PR 2 en `tasks.md`; la cobertura de lote parcial queda planificada en PR 3.
- Se corrigió la evidencia de cierre de PR 1: el 2026-08-14 se confirmaron 25 pruebas aprobadas con el comando indicado y árbol limpio.

## Archivos modificados

- `src/ingesta_clinica/dominio/privacidad.py`
- `src/ingesta_clinica/aplicacion/puertos/entrada.py`
- `src/ingesta_clinica/composicion.py`
- `tests/test_flujo_privacidad_pr2.py`
- `openspec/changes/ingesta-pdf-clinicos/tasks.md`
- `openspec/changes/ingesta-pdf-clinicos/apply-progress.md`

## Verificación

| Comando | Resultado |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/test_flujo_privacidad_pr2.py -q` | 6 aprobadas |
| `.venv/Scripts/python.exe -m pytest -q` | 31 aprobadas |
| `git diff --check` | sin errores de espacios |

## Desviaciones y limitaciones

- No hay implementación de procesamiento por lote en PR 2; por tanto su TRIANGULATE sólo queda satisfecho para los errores de extracción y validación aplicables sin lote. La cobertura de lote parcial se difiere a PR 3 y no se declara implementada.
- La anonimización es deliberadamente mínima y limitada a marcadores sintéticos; no declara cobertura clínica ni aptitud productiva.
- No se añadieron archivos, registros de contenido, base de datos, migraciones, colas, *brokers*, red ni UI.

## Trabajo restante

- PR 3 debe cubrir explícitamente el lote parcial junto con archivos no laboratorio, errores por archivo y lotes mixtos; no se inició esa cobertura en PR 2.
- PR 3/UI y todas las tareas tras sus puertas permanecen fuera de alcance.
- Acciones de ciclo de vida diferidas al padre: revisión del tamaño del diff de PR 2 y todas las puertas de calidad, persistencia, ecocardiografía, ECG y ML.

## Límite de revisión

El cambio se mantiene bajo el presupuesto de 400 líneas para el PR 2; su límite es privacidad y descarte en memoria. No se creó commit, push ni recibo de entrega.

---

# Progreso de aplicación: PR 3 — UI local y acuse seguro de lote

## Estado consumido

- Cambio: `ingesta-pdf-clinicos`; estado `apply=ready` autoritativo.
- Contexto de acción: `repo-local`, raíz y raíz de edición autorizada `D:\proyectos\anonimizacion`; sin advertencias.
- Alcance: exclusivamente PR 3 (secciones 3.1, 3.2 y cierre 3.3) en `feat/carga-manual-local`.
- El padre confirmó el gate de PR 2 para `95a3ec7`: 359 inserciones + 28 eliminaciones = 387 líneas, alcance alineado. La casilla correspondiente queda sin modificar por ser de propiedad `parent`.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3.1 carga y acuse | `tests/test_carga_local_pr3.py` | Unit | 32/32 | 9 fallos iniciales por módulos inexistentes; 1 fallo posterior para arrastre real | 9/9 y luego 11/11 | 10/10: lote mixto, parcial, no-laboratorio, fallo individual y código no permitido | 11/11: se aisló procesamiento por archivo sin cambiar salida |
| 3.2 límites locales | `tests/test_carga_local_pr3.py` | Unit / comprobación estática | 32/32 | Casos negativos de contenido prohibido escritos antes de producción | 10/10 | 11/11: inspección automatizada de dependencias laterales prohibidas | 11/11: UI queda como marcado estático mínimo |

## Trabajo completado

- Se creó `AdaptadorCargaLocal`, que invoca el puerto de entrada exactamente una vez por cada `bytes` recibido, en orden y de forma síncrona.
- `AcuseLoteSeguro` sólo publica `recibidos`, `procesados` y un código de catálogo permitido por archivo; códigos inesperados o errores individuales se reducen a `INGESTA_FALLIDA`.
- La interfaz es marcado HTML estático local con selección múltiple y zona de arrastre; no tiene transporte de red, API, autenticación, persistencia, temporales, cola, *broker* ni salida de contenido.
- Se marcaron como completas en `tasks.md` las nueve casillas de implementación de PR 3; se preservaron byte a byte las tareas de propiedad `parent`.

## Archivos modificados en PR 3

- `src/ingesta_clinica/adaptadores/entrada/__init__.py`
- `src/ingesta_clinica/adaptadores/entrada/carga_local.py`
- `src/ingesta_clinica/adaptadores/entrada/interfaz_local.py`
- `tests/test_carga_local_pr3.py`
- `openspec/changes/ingesta-pdf-clinicos/tasks.md`
- `openspec/changes/ingesta-pdf-clinicos/apply-progress.md`

## Verificación

| Comando | Resultado |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q` (línea base) | 32 aprobadas |
| `.venv/Scripts/python.exe -m pytest tests/test_carga_local_pr3.py -q` (RED) | 9 fallos esperados: módulos de entrada inexistentes |
| `.venv/Scripts/python.exe -m pytest tests/test_carga_local_pr3.py -q` (GREEN) | 9 aprobadas |
| `.venv/Scripts/python.exe -m pytest tests/test_carga_local_pr3.py -q` (TRIANGULATE) | 10 aprobadas |
| `.venv/Scripts/python.exe -m pytest tests/test_carga_local_pr3.py -q` (REFACTOR / límites y arrastre) | 11 aprobadas |
| `.venv/Scripts/python.exe -m pytest -q` | 43 aprobadas |
| `git diff --check` | sin errores de espacios |
| Revisión estática de `carga_local.py` e `interfaz_local.py` | no usan escritura, temporales, logs, red, colas ni almacenamiento |

## Desviaciones y limitaciones

- Sin framework ni servidor: la UI se mantiene como marcado estático local y el adaptador se prueba directamente contra el puerto hexagonal. Por ello no hay automatización de navegador ni puente HTTP; tampoco se creó API pública o servicio de red.
- El marcado ofrece los controles de selección múltiple/arrastre sin mostrar nombres ni resultados. La integración concreta de un host de navegador con el adaptador requeriría una decisión posterior que no amplíe los límites locales.
- No se usaron PDFs reales, OCR, datos clínicos, persistencia, evaluación habilitable, ECG, ecocardiografía ni ML.

## Trabajo restante

Las siguientes tareas de implementación siguen sin marcar por estar tras puertas no aprobadas:

- [ ] Tras la puerta, aplicar TDD estricto para un evaluador por campo y versión que use el corpus autorizado fuera del repositorio y publique sólo métricas técnicas permitidas. <!-- sdd-owner: implementation -->
- [ ] Tras la puerta, aplicar TDD estricto para persistir sólo los datos explícitamente autorizados y demostrar que PDF, texto fuente, PII/PHI y rechazos no se retienen. <!-- sdd-owner: implementation -->
- [ ] Tras cada puerta, planificar un PR independiente con RED, GREEN, TRIANGULATE y REFACTOR antes de implementar. <!-- sdd-owner: implementation -->

Acciones de ciclo de vida diferidas al padre: revisión de tamaño/alcance del PR 3 y todas las puertas de calidad, persistencia, ecocardiografía, ECG y ML.

## Límite de revisión / PR boundary

PR 3 comprende sólo adaptador de lote local, acuse minimizado, marcado estático y sus pruebas. Auditoría de contexto fresco del 2026-08-14 verificó con `git diff --no-index` que el nuevo código y pruebas suman 263 líneas antes de los registros SDD; el gate del padre (3.3) quedó marcado con esta evidencia. `docs/architecture/diagrama.md` (143 líneas) documenta legítimamente el alcance de PR 3 pero no fue declarado aquí a tiempo; se excluye deliberadamente de este commit y se publicará en un commit de documentación aparte para no mezclar alcance ni exceder el presupuesto de ~400 líneas.
