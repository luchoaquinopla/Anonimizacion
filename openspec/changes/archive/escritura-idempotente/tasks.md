# Tareas: escritura idempotente

Comando de test del proyecto: `pytest` (`pyproject.toml`, `testpaths = ["tests"]`). Carga: `pytest tests/carga/`.

**STRICT TDD MODE ACTIVO.** Cada fase se ejecuta en ciclos RED (test que falla por la razón correcta) → GREEN (mínimo código para pasar) → REFACTOR (limpieza sin cambiar comportamiento). Ningún ítem GREEN se marca sin su RED previo en rojo primero.

## Decisiones de diseño ya cerradas (no se replantean en esta fase)

- `clave_documento = HMAC(pepper, "documento|" + sha256.strip().lower())[:16 bytes]` en hex, en `pseudonimizacion/claves.py`, calcada del patrón de `generar_id_paciente`/`generar_id_medico`.
- El `sha256` crudo **MUST NOT** llegar a ningún destino de salida; solo la clave derivada.
- La identidad viaja en `_DocumentoResuelto` (privado de `pipeline/ejecutor.py`), no en `DocumentoParseado`: el parser no conoce la huella. `construir_registro` la recibe como argumento obligatorio de palabra clave.
- `RegistroAnonimizado.clave_documento: str | None = None` — opcional en el dataclass, obligatorio en `construir_registro`. Mismo precedente que `hora_estudio`/`precision_hora`.
- La unicidad vive en `estudio.clave_documento` (`UniqueConstraint`), nullable, sin backfill. Las mediciones la heredan por transacción — no llevan restricción propia (`resultado_laboratorio` es EAV, la unicidad no puede anclarse ahí).
- Reencuentro = ignorar (no reemplazar, no fallar). Contenido corregido = documento nuevo (otro `sha256`, otra clave).
- La idempotencia se decide **una sola vez**, en la clave, y la respetan los dos escritores, cada uno con el mecanismo de su medio: Postgres con `UNIQUE` + `SELECT`, el publicador con una guarda por `clave_documento` contra el manifiesto.
- Migración nueva: `0007_clave_documento`, `down_revision = "0006_estudio_y_hora"` (head real verificado). `op.batch_alter_table("estudio")` obligatorio: SQLite no soporta agregar `UNIQUE` con `ALTER TABLE`.
- Fuera de alcance: coordinación al cierre de corrida, cinecoronariografía, cambios en la ingesta, purga automática al reprocesar tras un cambio de parser, conectar `PublicadorBundles` a un llamador de producción, versionar `version_pipeline` por documento.

## Unidades de trabajo (work units)

Dos unidades, en este orden — costo de rollback distinto, mismo criterio que `hora-de-estudio`:

1. **Clave de documento en el dominio y su propagación, más la corrección del publicador y de `EscritorParquet.escribir_episodio`.** Se revierte sin pérdida: no toca el esquema, y el publicador vuelve a su comportamiento previo (defectuoso pero conocido). Incluye las tres compuertas de `tests/calibracion/` (una línea cada una).
2. **Columna `estudio.clave_documento`, restricción `UNIQUE`, migración `0007` y escritura condicional en Postgres.** Única con costo de esquema al revertir: el `downgrade` descarta las claves ya persistidas.

Los oráculos de `tests/carga/` (1.000 y 10.000) se corren **al final de la cadena**, después de que ambas unidades están completas. Verifican composición del corpus, no esquema — la tarea es correrlos y reportar, no asumir que hace falta regenerarlos.

---

## Fase 1: `generar_clave_documento` — derivación HMAC con namespace propio

- [x] 1.1 RED: en `tests/pseudonimizacion/test_claves.py` (o archivo equivalente existente), test que llama `generar_clave_documento(pepper, sha256)` — falla porque la función no existe.
- [x] 1.2 RED: test de estabilidad — el mismo `(pepper, sha256)` produce la misma clave en dos llamadas independientes (Requisito 1, "el mismo contenido produce la misma clave en dos corridas").
- [x] 1.3 RED: test que confirma que dos `sha256` distintos con el mismo pepper producen claves distintas (Requisito 1, segundo escenario).
- [x] 1.4 RED: test que confirma que la clave de documento es distinta del `sha256` crudo y distinta de `generar_id_paciente`/`generar_id_medico` con el mismo mensaje base — namespace propio (`"documento|"`), coherente con la convención de `claves.py`.
- [x] 1.5 GREEN: `generar_clave_documento(pepper: bytes, sha256: str) -> str` en `pseudonimizacion/claves.py`, usando `_hmac_hex(pepper, f"documento|{sha256.strip().lower()}")` — mismo patrón que las demás funciones del módulo.
- [x] 1.6 REFACTOR: confirmar que el docstring de módulo (lista de namespaces al inicio de `claves.py`) se actualiza para incluir `documento|`, igual que documenta los demás.

## Fase 2: dominio — `RegistroAnonimizado.clave_documento`

- [x] 2.1 RED: en `tests/dominio/test_modelos.py`, test que instancia `RegistroAnonimizado` con `clave_documento: str | None` y falla porque el dataclass todavía no acepta el campo.
- [x] 2.2 RED: test que confirma que `RegistroAnonimizado()` sin `clave_documento` sigue construyéndose (default `None`) — no debe romper fixtures existentes de otras fases.
- [x] 2.3 GREEN: agregar `clave_documento: str | None = None` al final de `RegistroAnonimizado` en `dominio/modelos.py`.
- [x] 2.4 REFACTOR: confirmar que ningún otro sitio del dominio hace destructuring posicional de `RegistroAnonimizado` que el campo nuevo (al final, con default) pudiera romper. Correr la suite completa de `tests/dominio/` y `tests/salida/` para confirmarlo.

## Fase 3: `construir_registro` — parámetro obligatorio, frontera donde hoy se pierde

- [x] 3.1 RED: en `tests/salida/test_constructor_registro.py`, test que llama `construir_registro(documento, claves, id_episodio=..., pepper=..., clave_documento="algún-valor")` y confirma que `RegistroAnonimizado.clave_documento` queda igual al valor pasado, sin transformarlo.
- [x] 3.2 RED: test que confirma que `construir_registro` sin `clave_documento` lanza `TypeError` (parámetro obligatorio de palabra clave, no un default silencioso — decisión de diseño explícita para que ningún llamador nuevo pueda omitirla).
- [x] 3.3 RED: en `tests/dominio/test_modelos.py` o `tests/salida/test_constructor_registro.py`, test que serializa un `RegistroAnonimizado` completo (los tres tipos de documento) y confirma que el `sha256` crudo no aparece en ningún campo, ni en `contenido` ni en `adicionales` (Requisito 1, "la huella cruda no llega a la salida").
- [x] 3.4 GREEN: agregar `clave_documento: str` como parámetro de palabra clave obligatorio en la firma de `construir_registro` (`salida/constructor_registro.py`), propagado tal cual al `RegistroAnonimizado` final, igual patrón que `hora_estudio`/`precision_hora`.
- [x] 3.5 GREEN: actualizar las tres compuertas de calibración (`tests/calibracion/compuerta_ecg.py:146`, `compuerta_laboratorio.py:207`, `compuerta_ecocardiograma.py:142`) — una línea cada una, pasando `clave_documento=generar_clave_documento(pepper, sha256_sintetico)` con una huella inventada de 64 hex. Ningún valor real: sha256 sintético fijo, documentado como tal en el propio test.
- [x] 3.6 REFACTOR: `pytest tests/calibracion/ tests/salida/test_constructor_registro.py` en verde; confirmar que el docstring de `constructor_registro.py` (lista de responsabilidades al inicio del módulo) menciona la propagación de `clave_documento`.

## Fase 4: `pipeline/ejecutor.py` — derivación en `_resolver_documento`, propagación en `_emitir`

- [x] 4.1 RED: en `tests/pipeline/test_ejecutor.py`, test que confirma que `_DocumentoResuelto` expone `clave_documento` — falla porque el campo no existe en el dataclass.
- [x] 4.2 RED: test de integración sobre `procesar_lote` con un `ItemLote` cuyo `artefacto.sha256` es conocido, que confirma que el `RegistroAnonimizado` recibido por el destino trae `clave_documento == generar_clave_documento(pepper, sha256)` — fija el recorrido completo `ItemLote.artefacto.sha256 → _resolver_documento → _emitir → construir_registro` antes de tocar código.
- [x] 4.3 GREEN: agregar `clave_documento: str` a `_DocumentoResuelto` (`pipeline/ejecutor.py`).
- [x] 4.4 GREEN: en `_resolver_documento`, calcular `clave_documento = generar_clave_documento(self._pepper, item.artefacto.sha256)` y pasarlo al construir `_DocumentoResuelto`.
- [x] 4.5 GREEN: en `_emitir` (línea ~424), agregar `clave_documento=resuelto.clave_documento` a la llamada a `self._construir_registro(...)`.
- [x] 4.6 REFACTOR: confirmar que el mensaje de cola no cambió — `ItemLote` sigue siendo `{id_documento, artefacto}` sin campo nuevo (Requisito 2, "la cola conserva su forma"); un test dedicado que inspecciona los campos del dataclass `ItemLote` y confirma que no ganó ninguno.

## Fase 5: Postgres — reprocesar no duplica (Requisito 3, primera mitad)

Nota: esta fase pertenece lógicamente a la Unidad 2 (toca esquema), pero se ubica aquí en la secuencia porque depende de que la Unidad 1 (Fases 1-4) ya haya propagado `clave_documento` hasta `RegistroAnonimizado`. Ver "Unidades de trabajo mapeadas a PRs" al final para el corte real de PRs.

- [x] 5.1 RED: en `tests/salida/test_modelos_orm.py`, test que intenta insertar dos filas `Estudio` con la misma `clave_documento` no nula contra SQLite en memoria y confirma que la segunda inserción lanza `IntegrityError` — falla porque la columna/restricción no existen todavía.
- [x] 5.2 RED: test que confirma que dos filas `Estudio` con `clave_documento=None` **no** colisionan entre sí (NULL no es igual a NULL en la restricción UNIQUE, ni en SQLite ni en Postgres) — fija explícitamente el comportamiento que permite que las filas legadas y los fixtures sintéticos convivan sin romper nada.
- [x] 5.3 GREEN: en `salida/modelos_orm.py`, agregar `clave_documento: Mapped[str | None] = mapped_column(String(32), nullable=True)` a `Estudio`, con `UniqueConstraint("clave_documento", name="uq_estudio_clave_documento")` en `__table_args__`.
- [x] 5.4 RED: en `tests/salida/destinos/test_postgres.py`, test que escribe el mismo `RegistroAnonimizado` (con `clave_documento` fija) tres veces consecutivas contra SQLite en memoria y confirma que existe **exactamente una** fila en `estudio` y una en la tabla de medición correspondiente — reproduce el experimento de la exploración, ahora como test que debe pasar (Requisito 3, primer escenario).
- [x] 5.5 RED: test que confirma que las tres escrituras del ítem anterior **no lanzan ninguna excepción** — un reprocesamiento es un caso normal, no una condición excepcional.
- [x] 5.6 RED: test que escribe dos documentos con `clave_documento` distinta pertenecientes al mismo episodio y confirma que quedan **dos** filas de `estudio` (Requisito 3, segundo escenario) — evita que la guarda sea, por error, por episodio en vez de por documento.
- [x] 5.7 RED: test que simula concurrencia — dos escrituras del mismo `clave_documento` sin que la primera haya hecho commit todavía cuando la segunda intenta insertar (mock de sesión, o dos sesiones abiertas contra el mismo engine SQLite con la primera sin cerrar transacción) — confirma que la segunda captura `IntegrityError`, hace rollback y retorna sin propagar la excepción (Requisito 3, tercer escenario, "la restricción resiste escritura concurrente").
- [x] 5.8 GREEN: en `destinos/postgres.py::escribir_registro`, al abrir la transacción, si `registro.clave_documento is not None`, hacer `SELECT` por `clave_documento` contra `Estudio`; si existe, retornar sin escribir nada (ni estudio ni mediciones). Si `registro.clave_documento is None`, conservar el comportamiento actual (inserta siempre — sin garantía, documentado ya en Fase 4 de `hora-de-estudio` como "sin relleno hacia atrás").
- [x] 5.9 GREEN: envolver el `insert`/`flush` del `Estudio` en `try/except IntegrityError`, capturar, hacer `sesion.rollback()` y tratar como "ya escrito" (retornar sin propagar) — la restricción `UNIQUE` es la autoridad final ante la carrera que el `SELECT` previo no cierra.
- [x] 5.10 REFACTOR: actualizar el docstring de `escribir_registro` — hoy dice explícitamente "No resuelve la idempotencia... reprocesar el mismo documento crea un `estudio` duplicado... Queda fuera de alcance" (línea 120-124); ese comentario queda obsoleto y debe reemplazarse por la descripción del mecanismo nuevo.

## Fase 6: migración `0007_clave_documento` (mismo gotcha de SQLite que `0006`)

- [x] 6.1 RED: en `tests/salida/test_migraciones.py`, test que corre `upgrade()` hasta `head` sobre SQLite en memoria y falla porque la revisión `0007` no existe todavía (o porque `_TABLAS_ESPERADAS`/columnas esperadas no calzan).
- [x] 6.2 GREEN: crear `migrations/versions/0007_clave_documento.py`, `down_revision = "0006_estudio_y_hora"`. `upgrade()`: `op.batch_alter_table("estudio")` → `add_column("clave_documento", sa.String(32), nullable=True)` + `create_unique_constraint("uq_estudio_clave_documento", ["clave_documento"])`. `batch_alter_table` obligatorio — SQLite no soporta agregar `UNIQUE` con `ALTER TABLE` directo.
- [x] 6.3 RED: test de `downgrade()` — corre `upgrade()` seguido de `downgrade()` sobre SQLite en memoria y confirma que el esquema vuelve al estado de `0006` (columna fuera, restricción fuera).
- [x] 6.4 GREEN: `downgrade()` — `op.batch_alter_table("estudio")` → `drop_constraint("uq_estudio_clave_documento", type_="unique")` + `drop_column("clave_documento")`.
- [x] 6.5 REFACTOR: correr el ciclo `upgrade`/`downgrade`/`upgrade` para confirmar idempotencia estructural, mismo patrón que la Fase 12.5 de `hora-de-estudio`.

## Fase 7: EscritorParquet — corrige la pérdida del bucle (Requisito 4)

Cambio de firma deliberado: rompe intencionalmente `tests/salida/test_publicador_bundles.py::test_parquet_de_episodio_mantiene_una_sola_fila_vigente` (línea 36-44, que hoy fija exactamente el comportamiento defectuoso — "una sola fila vigente" cuando debería haber tres). Ese test se reemplaza, no se ajusta cosméticamente: su nombre y su aserción describen el bug.

Nota de verificación: `tests/integracion/test_momento_estudio_ambos_destinos.py` (mencionado en proposal.md como afectado) usa `EscritorParquet.escribir()` (el método que anexa, sin cambios de firma) y `EscritorPostgres.escribir_episodio()` (método distinto, mismo nombre, otra clase) — **no** llama a `EscritorParquet.escribir_episodio()`. Confirmado por lectura directa del archivo antes de esta fase. Si `sdd-apply` encuentra lo contrario al tocar el código, tratarlo como descubrimiento nuevo, no como el mismo hallazgo.

- [x] 7.1 RED: en `tests/salida/destinos/test_parquet.py`, test que llama `escribir_episodio` con la **secuencia completa** de los tres `RegistroAnonimizado` de un episodio (ECG + laboratorio + eco) y confirma que el Parquet resultante tiene **tres** filas, una por documento — falla porque la firma actual recibe un único registro.
- [x] 7.2 GREEN: cambiar `EscritorParquet.escribir_episodio(self, registro: RegistroAnonimizado)` a `escribir_episodio(self, registros: Sequence[RegistroAnonimizado])`; construir la tabla completa (una fila por registro, mismos campos que hoy: `id_paciente`, `id_episodio`, `fecha_estudio`, `tipo_documento`, `version_esquema`) y escribirla de una vez, conservando el patrón atómico `write_table` a temporal + `replace`.
- [x] 7.3 GREEN: agregar `clave_documento` a la fila de `episodios/{id_episodio}.parquet` (columna nueva, string) — es la forma de reconciliar el Parquet contra `estudio.clave_documento` sin re-derivar todo el corpus (design.md, "la columna se mantiene").
- [x] 7.4 RED: en `tests/salida/destinos/test_parquet.py`, test que llama `EscritorParquet.escribir()` (el método que anexa, no `escribir_episodio`) con el **mismo** `RegistroAnonimizado` dos veces en el mismo lote y confirma que el dataset resultante tiene una sola fila por analito/medida — dedup por `clave_documento` dentro del lote recibido.
- [x] 7.5 GREEN: en `EscritorParquet.escribir()`, deduplicar `registros` por `clave_documento` antes de construir las filas — un `set`/`dict` en memoria; los registros con `clave_documento=None` no participan de la dedup (mismo criterio NULL-no-colisiona que en Postgres).
- [x] 7.6 REFACTOR: actualizar `tests/salida/test_publicador_bundles.py::test_parquet_de_episodio_mantiene_una_sola_fila_vigente` para llamar `escribir_episodio([registro])` (lista de uno) si sigue teniendo sentido como test de esta unidad, o eliminarlo si queda cubierto por el nuevo test de tres documentos de 7.1 — decidir según cobertura, documentar la decisión en `apply-progress.md`.

## Fase 8: `PublicadorBundles` — guarda por documento, no por directorio (Requisitos 4 y 5)

- [x] 8.1 RED: en `tests/salida/test_publicador_bundles.py`, test que publica un episodio con tres documentos de tipos distintos (ECG, laboratorio, eco) y confirma que el Parquet del episodio contiene los tres, con los tres tipos representados (Requisito 4, "episodio de tres estudios").
- [x] 8.2 RED: test que publica el mismo episodio dos veces seguidas con los mismos documentos y confirma que el contenido publicado (manifiesto + Parquet) es idéntico byte a byte entre ambas publicaciones — nada se agrega ni se pierde (Requisito 4, "republicar no altera el resultado").
- [x] 8.3 RED: test que publica un episodio con dos de sus tres documentos, luego lo republica incluyendo el tercero, y confirma que el manifiesto enumera los tres y el Parquet los contiene a los tres (Requisito 5, "llega el estudio que faltaba").
- [x] 8.4 RED: test que confirma que, al republicar sin novedades, el manifiesto **no se reescribe** (mismo `mtime`, o un sentinel de "no tocado") — solo se reescribe cuando hay unión nueva de documentos.
- [x] 8.5 GREEN: agregar `documentos: list[str]` (las `clave_documento` ordenadas) al manifiesto en `PublicadorBundles.publicar`.
- [x] 8.6 GREEN: cambiar la guarda — leer el manifiesto existente si el directorio ya existe; calcular qué `registros` traen una `clave_documento` que **no** figura en `documentos`. Si no hay novedades, no tocar nada (ni manifiesto ni Parquet) y retornar el mismo `destino`.
- [x] 8.7 GREEN: si hay novedades, recalcular la unión de `documentos`/`tipos_documento`, reescribir el manifiesto atómicamente (temporal + `replace`, mismo patrón ya usado para el directorio) y llamar `self._escritor_parquet.escribir_episodio(registros_union)` con la **secuencia completa** (todos los documentos del episodio, no solo los nuevos) — la firma nueva de la Fase 7 espera eso.
- [x] 8.8 RED: en `tests/salida/test_publicador_bundles.py`, test que confirma que un registro sin `clave_documento` (`None`) se trata como "siempre nuevo" en la guarda del publicador — no rompe, pero tampoco participa de la deduplicación (mismo criterio NULL-no-colisiona).
- [x] 8.9 GREEN: ajustar la guarda de 8.6 para el caso `clave_documento is None` según 8.8.
- [x] 8.10 REFACTOR: `pytest tests/salida/test_publicador_bundles.py tests/salida/destinos/test_parquet.py` en verde; confirmar que `publicar` sigue lanzando `ValueError` para lote vacío o de episodios mezclados (comportamiento previo, sin cambios).

## Fase 9: contenido corregido entra como documento nuevo (Requisito 7)

- [x] 9.1 RED: en `tests/pipeline/test_ejecutor.py` o `tests/salida/test_constructor_registro.py`, test que simula un documento corregido (mismo `id_documento`, `sha256` distinto) y confirma que produce una `clave_documento` distinta de la versión anterior — sin necesidad de código nuevo, es una consecuencia directa de Fases 1 y 4; el test fija el comportamiento explícitamente.
- [x] 9.2 (retomado en PR3, no en PR2: la restricción existe desde el PR2 pero el test de integración vive con los demás de cierre): test de integración contra Postgres que confirma que, con `clave_documento` distinta, la fila anterior de `estudio` se conserva y se agrega una fila nueva (Requisito 7, "el documento se corrige en el origen") — depende de la restricción `UNIQUE` de la Fase 5 (fuera de alcance de este PR); sin ella, Postgres ya inserta ambas filas hoy sin garantía real, así que el test no verificaría nada nuevo. Se retoma junto con la Fase 5 en PR2.
- [x] 9.3 GREEN: ajustes de wiring que falten (no debería requerir lógica nueva).
- [x] 9.4 REFACTOR: ninguno esperado; confirmar en `apply-progress.md` si este comportamiento salió gratis de las fases anteriores o si hizo falta algún ajuste no previsto.

## Fase 10: integración extremo a extremo — ambos destinos, ambos defectos cerrados

- [x] 10.1 RED: test de integración (SQLite en memoria + `tmp_path` para Parquet) que procesa el mismo documento **tres veces** de punta a punta (`EjecutorPipeline.procesar_lote`) y confirma que Postgres queda con una sola fila de `estudio` y sus mediciones, sin ninguna excepción no controlada.
- [x] 10.2 RED: test de integración que publica un episodio de tres documentos vía `PublicadorBundles.publicar` y confirma que el Parquet del episodio conserva los tres — el defecto original de la exploración, ahora cerrado end-to-end.
- [x] 10.3 GREEN: ajustes de wiring residuales, si aparecen (no debería requerir lógica nueva si las fases anteriores están completas).

## Fase 11: compuertas de calibración — cierre

- [x] 11.1 Confirmar que las tres compuertas (`compuerta_ecg.py`, `compuerta_laboratorio.py`, `compuerta_ecocardiograma.py`) quedaron actualizadas en la Fase 3, no como lote separado al final — auditoría, no trabajo nuevo si Fase 3 se siguió en orden.
- [x] 11.2 `pytest tests/calibracion/` completo en verde.

## Fase 12: oráculos de carga — revalidación, no regeneración asumida (al final de la cadena)

Los oráculos verifican **composición** del corpus (únicos/duplicados/aprobados/episodios/cuarentenas), no esquema. La clave de documento no cambia esos conteos. La tarea es correr y reportar — no asumir que hace falta regenerar, siguiendo el mismo criterio que `hora-de-estudio` Fase 16 (donde el oráculo tampoco se rompió pese a un cambio de schema).

- [x] 12.1 Correr `python -m tests.carga.ejecutar_corpus` (1.000 PDFs). Si la composición del corpus coincide con el oráculo existente, dejarlo intacto y reportar `oraculo_validado: true`. Si no coincide, investigar la causa antes de regenerar — un cambio de composición inesperado en este cambio sería una señal de bug, no de drift esperado.
- [x] 12.2 Confirmar sin regresión de tiempo/memoria frente a la última corrida validada (ver `openspec/changes/hora-de-estudio/tasks.md`, Fase 16, para los valores de referencia más recientes).
- [~] 12.3 PARCIAL — ver nota abajo. Correr `tests/carga/ejecutar_corpus_10000.py`: mismo criterio — composición idéntica, sin regresión a escala. Agregar el invariante nuevo que pide el diseño: `filas en estudio == documentos_aprobados` tras una pasada, y una segunda pasada sobre el mismo plan que no debe incrementar ninguna tabla (verifica el Requisito 3 a escala real, no solo con fixtures sintéticos).
  **La corrida se hizo y validó, pero el invariante nuevo NO se pudo verificar acá.** `tests/fixtures/corpus_piloto.py:153` usa `_DestinoMemoria`: el banco de carga nunca escribe una fila en SQL, así que no hay tabla `estudio` que contar. Verificarlo exigiría cambiar el banco para usar un destino real, lo cual además alteraría tiempo y memoria e invalidaría la comparación con todas las corridas anteriores. La idempotencia contra el escritor real queda cubierta por `tests/integracion/test_reprocesar_no_duplica.py`, que pasa por la fábrica de producción — a menor escala, pero con el escritor de verdad. El banco de carga corriendo sobre un cableado que producción no usa es un hallazgo propio, hermano del que ya se registró sobre el coordinador de episodios, y merece su propio cambio.
- [x] 12.4 `pytest` completo del repositorio en verde.

---

## Pronóstico de carga de revisión

| Campo | Valor |
|---|---|
| Líneas estimadas | 600–750 |
| Riesgo de presupuesto 400 líneas | High |
| PRs encadenados recomendados | Yes |
| División sugerida | PR1 (Unidad 1: dominio + propagación + publicador + Parquet, Fases 1-4 y 7-9) → PR2 (Unidad 2: ORM + migración `0007` + Postgres, Fases 5-6) → PR3 (integración end-to-end + calibración + carga, Fases 10-12) |
| Delivery strategy | no especificada por el orquestador — se asume `ask-on-risk` |
| Chain strategy | pending — requiere elección del usuario |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Por qué el alcance creció frente al diseño original de dos unidades

El diseño describe dos unidades por costo de reversión (dominio+publicador vs. esquema+Postgres), pero el **arreglo del publicador** (Fase 7-8) es, en superficie, tan grande como la Fase 1-4: toca la firma pública de `EscritorParquet.escribir_episodio`, el formato del manifiesto, la guarda de `PublicadorBundles`, y rompe deliberadamente un test existente que hoy fija el comportamiento defectuoso como si fuera correcto. Mapear las dos unidades de diseño a exactamente dos PRs concentraría casi 400 líneas en el primero. Por eso este pronóstico separa la Unidad 1 en dos PRs (dominio/propagación por un lado, Parquet/publicador por otro) sin violar el orden de dependencias: ambos preceden a la Unidad 2, y ninguno de los dos toca esquema.

### Unidades de trabajo mapeadas a PRs

| Unidad de diseño | Fases | PR | Notas |
|---|---|---|---|
| 1a — dominio + propagación | 1, 2, 3, 4, 9 (parcial) | PR1 | Autónoma, se revierte sin pérdida. Incluye las 3 compuertas de calibración. |
| 1b — Parquet + publicador | 7, 8 | PR1 o PR1.5 | Depende de 1a (necesita `clave_documento` en `RegistroAnonimizado`). Rompe deliberadamente un test existente — ver nota en Fase 7. Si PR1 solo ya se acerca al presupuesto de 400 líneas, separar en un PR propio antes de PR2. |
| 2 — esquema + Postgres | 5, 6 | PR2 | Depende de 1a. Único con costo de datos al revertir (migración `0007`). |
| Cierre | 9 (resto), 10, 11, 12 | PR3 | Depende de PR2 (necesita ambos destinos completos para el end-to-end y los oráculos). |

Nota sobre el tamaño: la estimación (600-750 líneas) ya asume la división en al menos 3 PRs (posiblemente 4 si 1a/1b se separan). Combinar la Unidad 1 completa en un solo PR excede el presupuesto de 400 líneas con alta probabilidad, sobre todo por el volumen de tests de concurrencia (Fase 5.7, mocks de sesión) y los tests de reescritura atómica del manifiesto (Fase 8).
