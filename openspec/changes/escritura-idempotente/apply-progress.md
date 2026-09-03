# Progreso de aplicación: escritura idempotente — PR1

Lote: **Fases 1, 2, 3, 4, 7, 8 y 9** (Unidad 1 completa: dominio + propagación +
corrección del publicador y de `EscritorParquet.escribir_episodio`). Fases 5, 6,
10, 11 y 12 quedan explícitamente FUERA de este lote (Postgres/migración/
integración end-to-end/calibración/carga — PR2 y PR3).

**Modo**: Strict TDD. Ciclo RED → GREEN → REFACTOR por fase, verificado con
`pytest` antes de cada GREEN.

## Tareas completadas

- [x] Fase 1 — `generar_clave_documento(pepper, sha256)` en `pseudonimizacion/claves.py`
- [x] Fase 2 — `RegistroAnonimizado.clave_documento: str | None = None`
- [x] Fase 3 — `construir_registro(..., clave_documento: str)` obligatorio de palabra clave
- [x] Fase 4 — `_DocumentoResuelto.clave_documento`, derivación en `_resolver_documento`, propagación en `_emitir`
- [x] Fase 7 — `EscritorParquet.escribir_episodio(registros: Sequence[...])` (secuencia completa, no pierde documentos) + dedup en `escribir()`
- [x] Fase 8 — `PublicadorBundles.publicar`: guarda por `clave_documento` contra el manifiesto, no por directorio
- [x] Fase 9 (parcial) — 9.1, 9.3, 9.4 completas; **9.2 diferido a PR2** (ver nota abajo)

## Tabla de evidencia TDD (RED → GREEN → REFACTOR)

| Fase | Test(s) | RED confirmado | GREEN | REFACTOR |
|---|---|---|---|---|
| 1.1–1.4 | `tests/pseudonimizacion/test_claves.py` (4 tests nuevos) | Sí — `ImportError: cannot import name 'generar_clave_documento'` | `generar_clave_documento` agregado a `claves.py` | Docstring de módulo actualizado con namespace `documento\|` |
| 2.1–2.2 | `tests/dominio/test_modelos.py` (2 tests nuevos) | Sí — `AttributeError: 'RegistroAnonimizado' object has no attribute 'clave_documento'` | Campo agregado con default `None` | `pytest tests/dominio/ tests/salida/` verde (86 tests), sin destructuring posicional roto |
| 3.1–3.3 | `tests/salida/test_constructor_registro.py` (3 tests nuevos + 10 existentes actualizados) | Sí — `TypeError: construir_registro() got an unexpected keyword argument 'clave_documento'` en los 10 tests existentes (porque se pasó el kwarg antes de que existiera) | Parámetro obligatorio agregado, propagado al `RegistroAnonimizado` | Docstring del módulo actualizado (punto 5, propagación de `clave_documento`); 3 compuertas de calibración actualizadas |
| 4.1–4.2 | `tests/pipeline/test_ejecutor.py` (2 tests nuevos) | Sí — `TypeError: _construir_ejecutor.<locals>.<lambda>() missing 1 required keyword-only argument: 'clave_documento'` | `_DocumentoResuelto.clave_documento`, derivación en `_resolver_documento`, propagación en `_emitir` | 4.6 (`ItemLote` sin campo nuevo) verificado con test dedicado, 18 tests de `test_ejecutor.py` en verde |
| 7.1 | `test_escribir_episodio_con_secuencia_completa_conserva_los_tres_documentos` | Sí — `AttributeError: 'list' object has no attribute 'id_episodio'` | Firma cambiada a `Sequence[RegistroAnonimizado]`, tabla completa en un solo `write_table`+`replace` | — |
| 7.3 | `test_escribir_episodio_incluye_clave_documento_por_fila` | Sí (mismo error que 7.1, corrida junto) | `clave_documento` agregado a la fila del episodio | — |
| 7.4–7.5 | `test_escribir_dedup_por_clave_documento_dentro_del_mismo_lote` | Sí — `assert 2 == 1` (sin dedup, escribía las dos) | `_deduplicar_por_clave_documento` en `EscritorParquet.escribir()` | `test_escribir_no_deduplica_registros_con_clave_documento_none` — **nota**: este test pasó en verde de entrada (no hubo RED real) porque, sin lógica de dedup, dos registros sin overlap de clave nunca se agrupaban; documentado aquí en vez de forzar un RED artificial |
| 7.6 | `test_publicador_bundles.py::test_parquet_de_episodio_con_un_solo_documento_republicado_sigue_teniendo_una_fila` | N/A (renombrado, no nuevo comportamiento) | Actualizado a `escribir_episodio([registro])` | Se conservó (no se eliminó): sigue siendo una regresión válida para el caso de un solo documento, distinta del nuevo test de 3 documentos |
| 8.1–8.4, 8.8 | `test_publicador_bundles.py` (6 tests nuevos) | 8.1, 8.3, 8.8: Sí (`KeyError: 'documentos'`). 8.2, 8.4: **pasaron en verde de entrada** — la guarda por directorio anterior ya evitaba tocar el manifiesto en un republicado sin novedades del mismo episodio completo; documentado aquí en vez de forzar RED artificial | Guarda por `clave_documento` contra manifiesto, unión atómica en republicación | 8.10 — `pytest tests/salida/test_publicador_bundles.py tests/salida/destinos/test_parquet.py` verde (21 tests); `ValueError` de lote vacío/episodios mezclados verificado sin cambios |
| 9.1 | `test_documento_corregido_mismo_id_documento_distinto_sha256_produce_clave_distinta` | **Pasó en verde de entrada** — comportamiento esperado y documentado explícitamente en tasks.md 9.3/9.4 ("no debería requerir código nuevo si Fases 1 y 4 están completas"); no es un fallo de proceso, es la consecuencia prevista por diseño | Ninguno necesario | 9.4: confirmado en esta tabla — el comportamiento salió gratis |

## Resultado de `pytest` (suite completa del repositorio)

```
516 passed, 1 skipped in 100.22s
```

El único `skipped` es preexistente y no relacionado con este cambio:
`tests/ingesta/test_fuente.py::test_fuente_local_omite_enlace...` — el entorno
Windows de esta corrida no otorga el privilegio para crear symlinks
(`WinError 1314`), condición del sistema operativo, no del código.

## Archivos modificados

| Archivo | Qué cambió |
|---|---|
| `src/anonimizacion/pseudonimizacion/claves.py` | `generar_clave_documento`, docstring de namespaces |
| `src/anonimizacion/dominio/modelos.py` | `RegistroAnonimizado.clave_documento` |
| `src/anonimizacion/salida/constructor_registro.py` | Parámetro obligatorio `clave_documento`, docstring |
| `src/anonimizacion/pipeline/ejecutor.py` | `_DocumentoResuelto.clave_documento`, derivación y propagación |
| `src/anonimizacion/salida/destinos/parquet.py` | `escribir_episodio` recibe secuencia completa; dedup en `escribir()`; columna `clave_documento` |
| `src/anonimizacion/salida/publicador_bundles.py` | Guarda por `clave_documento` contra manifiesto; escritura atómica del manifiesto |
| `tests/pseudonimizacion/test_claves.py` | 4 tests nuevos (Fase 1) |
| `tests/dominio/test_modelos.py` | 2 tests nuevos (Fase 2) |
| `tests/salida/test_constructor_registro.py` | 3 tests nuevos + 10 actualizados (Fase 3) |
| `tests/calibracion/compuerta_ecg.py`, `compuerta_laboratorio.py`, `compuerta_ecocardiograma.py` | `clave_documento` sintética agregada a cada llamada a `construir_registro` |
| `tests/pipeline/test_ejecutor.py` | 2 tests nuevos (Fase 4) + 1 test nuevo (Fase 9.1) + fakes actualizados |
| `tests/salida/destinos/test_parquet.py` | 5 tests nuevos (Fase 7) + helpers actualizados |
| `tests/salida/destinos/test_postgres.py` | Llamadas a `construir_registro` actualizadas (sin cambio de comportamiento; Postgres/Fase 5 fuera de alcance) |
| `tests/salida/test_publicador_bundles.py` | 6 tests nuevos (Fase 8) + 1 test renombrado/adaptado (7.6) |
| `tests/integracion/test_momento_estudio_ambos_destinos.py`, `test_salida_sin_pii.py` | Llamadas a `construir_registro` actualizadas (sin cambio de comportamiento) |
| `openspec/changes/escritura-idempotente/tasks.md` | `[x]` en Fases 1–4, 7–8, y 9 salvo 9.2 (diferido a PR2) |

## Commits de esta unidad (work units, todos con tests incluidos)

1. `feat(pseudonimizacion): agrega generar_clave_documento con namespace propio`
2. `feat(dominio): agrega clave_documento a RegistroAnonimizado`
3. `feat(salida): exige clave_documento en construir_registro`
4. `feat(pipeline): deriva y propaga clave_documento desde el sha256 del artefacto`
5. `fix(parquet): escribir_episodio recibe la secuencia completa, no pierde documentos`
6. `fix(publicador): guarda por clave_documento, no por directorio`
7. `test(pipeline): fija que un documento corregido produce clave distinta`

Ninguno pusheado ni con PR abierto — según instrucción explícita del lote.

## Desviaciones de diseño

Ninguna. El diseño (`design.md`) y las tareas (`tasks.md`) se siguieron sin
apartarse: la derivación por HMAC con namespace `"documento|"`, el campo
opcional en el dataclass pero obligatorio en `construir_registro`, la
propagación vía `_DocumentoResuelto`, y la guarda por `clave_documento` en
ambos escritores, tal como estaban especificados.

## Nota sobre 9.2 (diferido)

El ítem 9.2 pide un test de integración contra Postgres que confirme que un
documento corregido (clave distinta) agrega una fila nueva **sin pisar** la
anterior. Ese comportamiento depende de la restricción `UNIQUE` de la Fase 5
(fuera de alcance de este PR1): sin ella, `EscritorPostgres.escribir_registro`
ya inserta cualquier fila nueva sin ninguna guarda —así que un test contra
Postgres hoy no verificaría nada específico de este cambio, solo el
comportamiento preexistente y sin garantías de "siempre inserta". Se marca
`[ ]` en `tasks.md` con la nota "DIFERIDO A PR2" y se retoma junto con la Fase
5, cuando la guarda de unicidad exista y el test tenga algo real que afirmar.

## Gotcha verificado (según instrucción del lote)

Cambiar la firma de `EscritorParquet.escribir_episodio` rompió
`tests/salida/test_publicador_bundles.py` como estaba previsto (líneas
originales 40-41). Se actualizó en el mismo commit que el cambio de firma
(work unit 5). Se confirmó, además, que
`tests/integracion/test_momento_estudio_ambos_destinos.py` **no** llama a
`EscritorParquet.escribir_episodio()` — sus llamadas son
`EscritorPostgres.escribir_episodio()` (mismo nombre, clase distinta, método
con firma `(*, id_episodio, id_paciente, fecha_ancla)`) y `EscritorParquet.escribir()`
para Parquet. Ese archivo no requirió ningún cambio de comportamiento más allá
de agregar `clave_documento` a las llamadas de `construir_registro` (parámetro
obligatorio nuevo).

## Riesgos / notas para PR2

- La Fase 5 (Postgres) recibirá `clave_documento` ya propagado en
  `RegistroAnonimizado` — no necesita tocar nada de lo hecho en este PR1 más
  allá de agregar la columna, la restricción y la guarda de escritura.
- El ítem 9.2 debe resolverse como parte de PR2 (ver nota arriba).
- Los oráculos de `tests/carga/` (Fase 12) todavía no se corrieron: quedan
  para el final de la cadena, después de PR2, según lo que ya indica
  `tasks.md`.

## Siguiente paso recomendado

`sdd-apply` de nuevo para PR2 (Fases 5-6: columna `estudio.clave_documento`,
`UniqueConstraint`, migración `0007`, escritura condicional en Postgres,
incluyendo el ítem 9.2 diferido).

## Lote 2 (PR2) — unicidad y escritura condicional

Fases 5 y 6 completas. `pytest` completo: 526 pasados, 1 omitido.

### Qué se hizo

- `Estudio.clave_documento` (`String(32)`, nullable) con
  `UniqueConstraint("clave_documento", name="uq_estudio_clave_documento")`.
- `migrations/versions/0007_clave_documento.py`, encadenada sobre
  `0006_estudio_y_hora`, con `op.batch_alter_table` porque SQLite no soporta
  agregar una restricción `UNIQUE` con `ALTER TABLE` directo. Tests de
  `upgrade`, `downgrade` y del ciclo completo.
- `escribir_registro` con guarda de dos capas: consulta previa por
  `clave_documento` para el caso normal, y `IntegrityError` capturado como
  autoridad final ante la carrera.

### Desvío respecto del plan, con su causa

El plan proponía la consulta previa **antes** de abrir la transacción
(`SELECT` y luego `with sesion.begin()`). Eso no funciona: `sesion.scalar`
abre una transacción implícita, y `begin()` después falla con
`InvalidRequestError: A transaction is already begun on this Session`.

Se unificó todo en una sola transacción, lo cual además es más correcto:
separar la consulta de la inserción ampliaría la ventana de la carrera sin
ganar nada.

También se descartó el `sesion.rollback()` explícito del plan: el gestor de
contexto de `sesion.begin()` ya revierte al propagar la excepción, así que
llamarlo de nuevo es ruido.

### Comportamiento sin clave

Un registro con `clave_documento` ausente conserva el comportamiento anterior e
inserta siempre. No hay garantía posible: la clave se deriva del contenido y una
fila escrita antes de este cambio no puede recuperarla sin releer el documento
original. Queda fijado por test.

### Qué queda

Fases 10 a 12 (PR3): integración extremo a extremo, compuertas de calibración y
revalidación de los ensayos de carga, más el ítem 9.2 diferido desde el PR1.

## Lote 3 (PR3) — cierre

Fases 10 y 11 completas, Fase 12 parcial con causa declarada. `pytest` completo:
529 pasados, 1 omitido.

### Fases 10 y 11

Tres tests de integración, todos en verde sin código nuevo: los arreglos ya
estaban en los dos lotes anteriores. Son confirmación de punta a punta y guardia
de regresión, no comportamiento nuevo, y la fase lo anticipaba así.

El test de duplicación corre **por `tareas.construir_fabrica_ejecutor`**, la raíz
de composición de producción, no armando el ejecutor a mano.

Las tres compuertas de calibración ya llevaban `clave_documento` desde la Fase 3.

### Fase 12 — ensayos de carga

| Ensayo | Métrica | Anterior | Ahora | Diferencia |
|---|---|---|---|---|
| 1.000 | Tiempo | 222,74 s | 220,47 s | −1,0 % |
| 1.000 | Memoria pico | 147.136.512 B | 147.099.648 B | −0,03 % |
| 10.000 | Tiempo | 41,1 min | 40,95 min | −0,4 % |
| 10.000 | Memoria pico | 285,9 MiB | 304,2 MiB | +6,4 % |

Composición idéntica en ambos, `oraculo_validado: true`, 0 fallos, 0 reintentos,
`pii_en_salida: 0`. Ningún oráculo se rompió ni hubo que regenerarlo.

Sobre el +6,4 % de memoria a 10.000: las tres últimas corridas dieron 301,3 /
285,9 / 304,2 MiB. La dispersión entre corridas es del mismo orden que la
diferencia observada, así que se reporta como variación, no como regresión. No
se ajusta ninguna constante para disimularla.

### Lo que NO se pudo verificar, y por qué

La tarea 12.3 pedía un invariante nuevo a escala real: `filas en estudio ==
documentos_aprobados` tras una pasada, y una segunda pasada que no incremente
ninguna tabla.

**No es verificable en el banco de carga.** `tests/fixtures/corpus_piloto.py:153`
usa `_DestinoMemoria`: el banco nunca escribe una fila en SQL, así que no existe
la tabla que habría que contar. Hacerlo posible exigiría cambiar el banco para
usar un destino real, lo cual agregaría miles de escrituras a SQLite, alteraría
tiempo y memoria, e invalidaría la comparación con todas las corridas previas.

La idempotencia contra el escritor real está cubierta por
`tests/integracion/test_reprocesar_no_duplica.py`, que pasa por la fábrica de
producción: menor escala, pero escritor de verdad.

Que el banco de carga corra sobre un cableado que producción no usa es un
hallazgo por derecho propio, hermano del que ya se registró sobre el coordinador
de episodios. Merece su propio cambio y no se resuelve acá.

### Estado del cambio

`escritura-idempotente` completo: 12 fases, 3 PRs, con la salvedad declarada de
la 12.3.

