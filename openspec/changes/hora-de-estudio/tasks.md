# Tareas: hora del estudio

Comando de test del proyecto: `pytest` (`pyproject.toml`, `testpaths = ["tests"]`). Carga: `pytest tests/carga/`.

**STRICT TDD MODE ACTIVO.** Cada fase se ejecuta en ciclos RED (test que falla por la razón correcta) → GREEN (mínimo código para pasar) → REFACTOR (limpieza sin cambiar comportamiento). Ningún ítem GREEN se marca sin su RED previo en verde... es decir, en rojo primero.

## Decisiones de diseño ya cerradas (no se replantean en esta fase)

- Tabla nueva `estudio` con `(id_estudio, id_episodio, tipo_documento, fecha_estudio, hora_estudio, precision_hora)`; `id_estudio` FK **nullable** en `medicion_ecg`, `resultado_laboratorio`, `medicion_eco`. Aditiva, sin backfill.
- `hora_estudio: sa.Time` → `TIME WITHOUT TIME ZONE`, naive por construcción.
- `precision_hora` (`AUSENTE | MINUTO | SEGUNDO`) es un campo explícito del dominio, no derivable del valor de `hora_estudio`.
- Cuarentena es terminal: un documento que falla en reconciliación nunca produce fila en `estudio`.
- Migración nueva: `0006_estudio_y_hora`, `down_revision = "0005_tamano_y_tope_cuarentena"` (head único verificado).

## Unidades de trabajo (work units)

Dos unidades, en este orden — el diseño las fija así por costo de rollback distinto y ese orden se respeta:

1. **Dominio + parseo + reconciliación + Parquet.** Se revierte solo, sin pérdida de datos. Incluye las tres compuertas de `tests/calibracion/` migradas junto con el parser que califican — nunca después.
2. **`Estudio` + ORM + migración `0006` + escritor Postgres.** Única unidad con costo de datos al revertir (la migración de bajada borra `hora_estudio`/`fecha_estudio` ya escritas).

Los oráculos de `tests/carga/` (1.000 y 10.000 PDFs) se regeneran y corren **al final de la cadena**, después de que ambas unidades están completas: dependen del campo nuevo en ambos destinos (SQL y Parquet).

## Fase 1: dominio — `PrecisionHora` y campos nuevos

- [ ] 1.1 RED: en `tests/dominio/test_modelos.py` (o archivo equivalente existente), test que instancia `DocumentoParseado` y `RegistroAnonimizado` con `hora_estudio: time | None` y `precision_hora: PrecisionHora`, y falla porque el dataclass todavía no acepta esos campos.
- [ ] 1.2 RED: test que construye `DocumentoParseado` con `fecha_estudio` y `hora_estudio` ambos presentes y verifica que `fecha_estudio` sigue siendo `date` sin alteración (Requirement: "Campo de hora opcional, separado de la fecha", spec `momento-del-estudio`).
- [ ] 1.3 GREEN: crear `src/anonimizacion/dominio/precision_hora.py` — `class PrecisionHora(str, Enum)` con `AUSENTE`, `MINUTO`, `SEGUNDO`.
- [ ] 1.4 GREEN: en `dominio/modelos.py`, agregar `hora_estudio: time | None = None` y `precision_hora: PrecisionHora = PrecisionHora.AUSENTE` a `DocumentoParseado` y a `RegistroAnonimizado` (defaults para no romper construcciones existentes en tests de otras fases del pipeline).
- [ ] 1.5 REFACTOR: revisar que ningún otro sitio del dominio asuma que estos dos dataclasses solo tienen los campos previos (p. ej. destructuring posicional); ajustar si aparece.

## Fase 2: normalización de hora sin inferencia

- [ ] 2.1 RED: en `tests/reconciliacion/test_normalizacion.py`, tabla de casos para una función `normalizar_hora_iso` que todavía no existe: acepta `"08:45:00"` → `"08:45:00"`, acepta `"08:45"` → `"08:45"`, rechaza `"8:45"` (sin cero relativo — confirmar contra el formato real del documento antes de decidir si se acepta; si el layout real trae hora sin cero relativo, agregarlo como caso aceptado en vez de rechazado), rechaza `"25:00"`, rechaza cualquier string no numérico.
- [ ] 2.2 GREEN: `normalizar_hora_iso(valor: str) -> tuple[str, PrecisionHora]` en `reconciliacion/normalizacion.py`, espejo de `normalizar_fecha_iso`: prueba `%H:%M:%S` (devuelve `SEGUNDO`) y `%H:%M` (devuelve `MINUTO`) en ese orden, levanta `ValueError` si ninguno matchea. Cero inferencia, cero corrección de formatos ambiguos.
- [ ] 2.3 REFACTOR: confirmar que la firma no colisiona con el patrón existente de `normalizar_fecha_iso` (misma convención de excepción, mismo estilo de docstring).

## Fase 3: ECG — dejar de truncar la hora

- [ ] 3.1 RED: en `tests/calibracion/test_compuerta_ecg.py`, agregar la aserción de hora contra la muestra real: un ECG con header `DD-MON-YYYY HH:MM:SS` produce `hora_estudio` con precisión de segundo, valor exacto verificado campo por campo (compuerta estricta, no aproximada). Este RED se agrega **en el mismo work unit que el parser** (Fase 3), nunca después.
- [ ] 3.2 RED: en `tests/parseo/test_ecg_mortara.py`, test unitario que falla si `_parsear_fecha` vuelve a truncar: dado un header con hora, el `DocumentoParseado` resultante expone `hora_estudio` no nulo con precisión `SEGUNDO`.
- [ ] 3.3 GREEN: modificar `_parsear_fecha` en `parseo/ecg_mortara.py:234` — de devolver solo `date` a devolver `(date, time)`, reutilizando la porción horaria ya capturada en `header["fecha"]` (patrón `_CAMPOS_HEADER["fecha"]`, línea 93, ya matchea `HH:MM:SS` completo). Usar `normalizar_hora_iso` (Fase 2) sobre la porción horaria para obtener `hora_estudio` y `precision_hora`.
- [ ] 3.4 GREEN: agregar `ReferenciaCampo("ecg.hora_estudio", 1, "ecg.hora_estudio")` a `fuentes` en `ParseadorEcgMortara.parsear`.
- [ ] 3.5 REFACTOR: revisar que `ContenidoEcg` no necesite el campo (la hora vive en `DocumentoParseado`, no en el contenido tipado por tipo de documento) y que `adicionales` no siga conteniendo la porción horaria del header por duplicado.

## Fase 4: ECG — procedencia anclada al timestamp completo (gotcha 1)

- [ ] 4.1 RED: en `tests/reconciliacion/test_ecg_mortara.py`, test que agrega el `id_campo` `"ecg.hora_estudio"` al whitelist sin patrón de inventario correspondiente y confirma `COBERTURA_INCOMPLETA` — fija el comportamiento antes de agregar el patrón.
- [ ] 4.2 RED: test que agrega un patrón de inventario **suelto** (`\d{2}:\d{2}:\d{2}` sin anclar al timestamp completo) contra un header ECG real y confirma que produce `COBERTURA_AMBIGUA` porque también matchea dentro del patrón de institución (`_PATRONES_INVENTARIO` en `reconciliacion/ecg_mortara.py:94`, patrón de fecha completo que incluye institución). Este test documenta el gotcha del diseño y debe fallar de la forma esperada (ambigüedad), no pasar por accidente.
- [ ] 4.3 GREEN: en `dominio/referencias.py`, agregar `"ecg.hora_estudio": frozenset({"ecg.hora_estudio"})` a `REFERENCIAS_PERMITIDAS`.
- [ ] 4.4 GREEN: en `reconciliacion/ecg_mortara.py`, agregar a `_PATRONES_INVENTARIO` un patrón anclado al timestamp **completo** (reutilizando el mismo grupo que `ecg.fecha_estudio`, línea 21: `\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2}`) que capture selectivamente la porción horaria, de forma que no colisione con el patrón de institución (línea 94, que también matchea `\d{2}:\d{2}:\d{2}\s+.+`). Agregar rama correspondiente en `_asociacion_ecg` que valide el valor de hora contra ese mismo ancla.
- [ ] 4.5 GREEN: incluir `("ecg.hora_estudio", 0): <hora formateada HH:MM:SS>` en el diccionario `valores` de `ReconciliadorEcgMortara.reconciliar`.
- [ ] 4.6 REFACTOR: correr `verificar_cobertura` directo (test dedicado) confirmando que el 1:1 se sostiene con el `id_campo` nuevo, sin `COBERTURA_AMBIGUA` ni `COBERTURA_INCOMPLETA` contra un documento real.

## Fase 5: laboratorio — promover `hora_extraccion` a campo tipado

- [ ] 5.1 RED: en `tests/calibracion/test_compuerta_laboratorio.py`, agregar la aserción de hora contra la muestra real: un laboratorio con `Hora de Extracción: HH:MM` produce `hora_estudio` con precisión `MINUTO`, valor exacto. En el mismo work unit que este parser, nunca después.
- [ ] 5.2 RED: en `tests/parseo/test_laboratorio_general.py`, test que confirma que `hora_extraccion` **ya no aparece** en `documento.adicionales` una vez promovido (hoy sale de `_CAMPOS_HEADER` línea 127 hacia `adicionales` sin tipo — confirmar el estado actual con un test que hoy pasa y luego invertirlo tras el GREEN).
- [ ] 5.3 GREEN: en `parseo/laboratorio_general.py`, extraer `header["hora_extraccion"]` (ya capturado por el patrón existente, línea 127) y normalizarlo con `normalizar_hora_iso` para poblar `hora_estudio`/`precision_hora` del `DocumentoParseado`; excluirlo de `adicionales` (agregar `"hora_extraccion"` a la tupla de claves excluidas, línea 412).
- [ ] 5.4 GREEN: agregar `ReferenciaCampo("laboratorio.hora_extraccion", <página del header>, "laboratorio.hora_extraccion")` a `fuentes`.
- [ ] 5.5 REFACTOR: confirmar que un laboratorio sin `Hora de Extracción:` en el header (si existiera esa variante) produce `precision_hora = AUSENTE` sin romper el parseo — agregar caso si la muestra real lo permite verificar; si no hay muestra sin el campo, documentar la suposición en un comentario y dejarlo para una calibración futura.

## Fase 6: laboratorio — `validador_asociacion` anclado (gotcha 2, la parte frágil)

- [ ] 6.1 RED: en `tests/reconciliacion/test_laboratorio_general.py`, test que reconcilia un laboratorio real cuya página trae el valor de hora suelto (p. ej. `08:45` aparece cero veces exacto, o aparece dentro de otro campo con distinto formato) **sin** `validador_asociacion`, y confirma que produce `VALOR_DISCREPANTE` o `EVIDENCIA_AMBIGUA` — reproduce el bug documentado en el diseño antes de arreglarlo (hoy `reconciliar_referencias` se llama sin `validador_asociacion` en `laboratorio_general.py:208`, cae en `pagina.count(valor) == 1`, `_comun.py:51`).
- [ ] 6.2 RED: test que confirma que, con el `validador_asociacion` nuevo aplicado, el mismo documento reconcilia sin error — la hora se ancla al rótulo `Hora de Extracción:` y no a una coincidencia suelta en la página.
- [ ] 6.3 GREEN: en `reconciliacion/laboratorio_general.py`, agregar una función `_asociacion_laboratorio` (siguiendo el patrón de `_asociacion_ecg` en `reconciliacion/ecg_mortara.py:55`) que busque el rótulo `Hora(?:\s+de)?\s+Extracci[oó]n:` en la página y valide que el valor esperado aparece inmediatamente después de ese rótulo (mismo criterio de anclaje que usa el ECG para sus medidas).
- [ ] 6.4 GREEN: pasar `validador_asociacion=_asociacion_laboratorio` en la llamada a `reconciliar_referencias` de `ReconciliadorLaboratorioGeneral.reconciliar` (línea 207) — solo para el selector de hora, sin afectar la ruta existente de `laboratorio.resultado` (que sigue usando `ids_con_asociacion_estructurada`).
- [ ] 6.5 GREEN: agregar `"laboratorio.hora_extraccion": frozenset({"laboratorio.hora_extraccion"})` a `REFERENCIAS_PERMITIDAS` y el patrón de inventario correspondiente en `_PATRONES_INVENTARIO`/`inventariar` de `ReconciliadorLaboratorioGeneral`, anclado al mismo rótulo (evita el mismo riesgo de patrón suelto que el gotcha 1).
- [ ] 6.6 REFACTOR: correr `verificar_cobertura` directo confirmando 1:1 sostenido para `laboratorio.hora_extraccion` contra la muestra real; confirmar contra la muestra que el rótulo elegido no matchea la columna de resultados anteriores (riesgo anotado en la exploración y en las preguntas abiertas del diseño).

## Fase 7: eco — ausencia explícita, nunca un default

- [ ] 7.1 RED: en `tests/calibracion/test_compuerta_ecocardiograma.py`, agregar la aserción **negativa**: un eco parseado produce `precision_hora == PrecisionHora.AUSENTE` y `hora_estudio is None`, y el test falla explícitamente si en algún momento aparece `time(0, 0)` o cualquier hora no-`None`. En el mismo work unit que este parser.
- [ ] 7.2 RED: en `tests/parseo/test_eco_doppler.py`, test que confirma que `ParseadorEcoDoppler.parsear` nunca agrega `ReferenciaCampo` de hora ni `id_campo` de hora a `fuentes` (el eco no declara ninguno — sin referencia y sin hallazgo el 1:1 de cobertura se sostiene solo).
- [ ] 7.3 GREEN: en `parseo/eco_doppler.py`, `parsear` deja `hora_estudio=None` y `precision_hora=PrecisionHora.AUSENTE` explícitos al construir `DocumentoParseado` (usando los defaults de la Fase 1, pero documentando la intención con un comentario que cite el Requirement de la spec, no dejarlo implícito).
- [ ] 7.4 REFACTOR: confirmar que ningún cambio de Fase 1 rompe el resto de tests de eco (defaults no deben alterar el comportamiento existente de `ParseadorEcoDoppler`).

## Fase 8: hora ilegible va a cuarentena, no a ausencia silenciosa

- [ ] 8.1 RED: en `tests/parseo/test_ecg_mortara.py` y `tests/parseo/test_laboratorio_general.py`, test con un valor de hora presente pero con formato irreconocible (p. ej. `"25:99"` o texto no numérico en el campo de hora) — confirma que el documento se aparta a cuarentena (`ErrorParseo` con código que identifica el campo de hora como causa) y que el `DocumentoParseado` **no** se construye con `precision_hora = AUSENTE` para ese caso (Requirement: "Hora ilegible va a cuarentena, no a ausencia silenciosa").
- [ ] 8.2 GREEN: en `parseo/ecg_mortara.py` y `parseo/laboratorio_general.py`, capturar el `ValueError` de `normalizar_hora_iso` y relanzar `ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)` (mismo patrón que el manejo actual de `_parsear_fecha`), en vez de dejar pasar el valor como ausencia.
- [ ] 8.3 REFACTOR: confirmar que el mensaje/código de cuarentena no filtra el valor crudo de hora (coherente con `dominio/errores.py`, nunca propagar contenido del documento).

## Fase 9: propagación a la salida (`salida/`)

- [ ] 9.1 RED: en `tests/salida/test_constructor_registro.py`, test que confirma que `construir_registro` propaga `hora_estudio` y `precision_hora` del `DocumentoParseado` al `RegistroAnonimizado` sin transformarlos.
- [ ] 9.2 GREEN: agregar `hora_estudio: time | None` y `precision_hora: PrecisionHora` a `RegistroAnonimizado` si no quedó cubierto por la Fase 1 (confirmar), y propagarlos en `construir_registro` (`salida/constructor_registro.py`, cerca de la construcción final del `RegistroAnonimizado`, línea ~191).
- [ ] 9.3 REFACTOR: revisar que `modelos_salida.py` no necesite cambios — la hora vive en `RegistroAnonimizado`, no en los payloads `ContenidoXSalida` (el pivote de esos payloads es por tipo de documento, la hora es transversal).

## Fase 10: Parquet — schema explícito (gotcha 4)

- [ ] 10.1 RED: en `tests/salida/destinos/test_parquet.py`, test que escribe un lote **compuesto enteramente por ecocardiogramas** (todos con `precision_hora = AUSENTE`, `hora_estudio = None`) y confirma que la columna `hora_estudio` en el Parquet resultante NO queda con tipo `null` inferido — debe tener un tipo string explícito, para no chocar con la partición de ECG al leer el dataset combinado. Este test debe fallar contra el código actual (que usa `pa.Table.from_pylist` sin schema) antes del GREEN.
- [ ] 10.2 GREEN: en `destinos/parquet.py::_escribir_dataset`, declarar un `pa.schema` explícito que incluya `hora_estudio` (`pa.string()`, formato ISO o `None`) y `precision_hora` (`pa.string()`) para los tres datasets (`laboratorio`, `ecg`, `eco_medidas`/`eco_texto` si aplica), pasado a `pa.Table.from_pylist(filas, schema=...)`.
- [ ] 10.3 GREEN: agregar `hora_estudio`/`precision_hora` a los diccionarios de fila en `_filas_laboratorio`, `_filas_ecg` (y a `eco_medidas`/`eco_texto` si el diseño lo pide — confirmar contra el flujo del dato: el eco propaga `precision_hora=AUSENTE` igual que los demás).
- [ ] 10.4 REFACTOR: test de integración que lee de vuelta un dataset combinado (partición ECG + partición eco) y confirma que no hay conflicto de tipo de columna entre particiones.

## Fase 11: ORM — tabla `Estudio` y FK nullable

- [ ] 11.1 RED: en `tests/salida/test_modelos_orm.py`, test que instancia `Estudio(id_episodio=..., tipo_documento=..., fecha_estudio=..., hora_estudio=..., precision_hora=...)` contra SQLite en memoria y falla porque la clase no existe.
- [ ] 11.2 RED: test que confirma que `MedicionEcg`, `ResultadoLaboratorio`, `MedicionEco` aceptan `id_estudio` nullable sin romper filas existentes sin ese valor.
- [ ] 11.3 GREEN: en `salida/modelos_orm.py`, agregar clase `Estudio` (`__tablename__ = "estudio"`, `id_estudio: Mapped[int]` autoincremental PK, `id_episodio` FK a `episodio.id_episodio` con índice, `tipo_documento: Mapped[str]`, `fecha_estudio: Mapped[date]`, `hora_estudio: Mapped[time | None]` con `sa.Time`, `precision_hora: Mapped[str]`); docstring que documente naive/sin huso, siguiendo la convención de docstrings del módulo.
- [ ] 11.4 GREEN: agregar `id_estudio: Mapped[int | None] = mapped_column(Integer, ForeignKey("estudio.id_estudio"), nullable=True)` a `MedicionEcg`, `ResultadoLaboratorio`, `MedicionEco`.
- [ ] 11.5 REFACTOR: confirmar que `id_episodio` se conserva sin cambios en las tres tablas de mediciones (ninguna query existente se rompe).

## Fase 12: migración `0006_estudio_y_hora` (gotcha 3, SQLite sin ALTER FK)

- [ ] 12.1 RED: test de migración (`tests/migrations/` o equivalente ya existente en el repo — confirmar convención) que corre `upgrade()` sobre SQLite en memoria y falla porque la revisión `0006` no existe todavía.
- [ ] 12.2 GREEN: crear `migrations/versions/0006_estudio_y_hora.py`, `down_revision = "0005_tamano_y_tope_cuarentena"`. `upgrade()`: `op.create_table("estudio", ...)` con índice en `id_episodio`; los tres `op.add_column(..., sa.Column("id_estudio", sa.Integer(), sa.ForeignKey("estudio.id_estudio"), nullable=True))` **dentro de `op.batch_alter_table(<tabla>)`** — SQLite no soporta `ALTER TABLE` con FK y los tests corren contra SQLite en memoria.
- [ ] 12.3 RED: test de `downgrade()` — corre `upgrade()` seguido de `downgrade()` sobre SQLite en memoria y confirma que el esquema vuelve al estado de `0005` (columnas `id_estudio` fuera, tabla `estudio` dropeada).
- [ ] 12.4 GREEN: `downgrade()` — los tres `op.drop_column` (también en `batch_alter_table`) y `op.drop_table("estudio")`.
- [ ] 12.5 REFACTOR: correr el ciclo completo `upgrade`/`downgrade`/`upgrade` para confirmar idempotencia estructural (no de datos — eso está fuera de alcance, ver "Preguntas abiertas" del diseño).

## Fase 13: escritor Postgres — inserta `estudio` y enlaza mediciones

- [ ] 13.1 RED: en `tests/salida/destinos/test_postgres.py`, test que llama a un método nuevo (p. ej. `escribir_estudio` o integrado en `escribir_registro`) y confirma que se crea una fila en `estudio` con `fecha_estudio`/`hora_estudio`/`precision_hora` correctos, y que la medición correspondiente (`medicion_ecg`/`resultado_laboratorio`/`medicion_eco`) queda con `id_estudio` apuntando a esa fila.
- [ ] 13.2 RED: test que confirma que un eco con `precision_hora = AUSENTE` produce una fila `estudio` con `hora_estudio = NULL` y `precision_hora = 'ausente'` — nunca `00:00:00`.
- [ ] 13.3 GREEN: en `destinos/postgres.py`, agregar `escribir_estudio(registro: RegistroAnonimizado) -> int` (devuelve `id_estudio`) que inserta en `Estudio` y llamarlo desde `escribir_registro` antes de despachar por tipo, pasando el `id_estudio` resultante a `_escribir_ecg`/`_escribir_laboratorio`/`_escribir_eco`.
- [ ] 13.4 REFACTOR: anotar explícitamente en el docstring del método (o en un comentario) que esto **no** resuelve la idempotencia de `escribir_registro` — un reprocesamiento crea una fila `estudio` duplicada, igual que ya pasa con las mediciones; queda fuera de alcance por decisión ya tomada en el diseño.

## Fase 14: integración extremo a extremo — ausencia sobrevive a ambos destinos

- [ ] 14.1 RED: test de integración (SQLite en memoria + `tmp_path` para Parquet) que procesa los tres tipos de documento (ECG, laboratorio, eco) y confirma que `hora_estudio`/`precision_hora` llegan idénticos a `estudio` (SQL) y al dataset Parquet correspondiente, incluida la fila de eco con `NULL`/`AUSENTE` en ambos destinos.
- [ ] 14.2 GREEN: ajustes de wiring que falten entre las fases anteriores para que el flujo completo pase (no debería requerir lógica nueva si las fases previas están completas — este ítem es red de seguridad, no implementación nueva).

## Fase 15: compuertas de calibración — cierre

- [ ] 15.1 Confirmar que las tres compuertas (`test_compuerta_ecg.py`, `test_compuerta_laboratorio.py`, `test_compuerta_ecocardiograma.py`) quedaron actualizadas dentro de sus fases respectivas (3, 5, 7) y no como un lote separado al final — auditoría, no trabajo nuevo si las fases anteriores se siguieron en orden.
- [ ] 15.2 `pytest tests/calibracion/` completo en verde.

## Fase 16: oráculos de carga — regeneración y corrida (al final de la cadena)

- [ ] 16.1 Regenerar el oráculo de `tests/carga/test_ejecutar_corpus.py` (1.000 PDFs): el schema de Parquet cambió (Fase 10), así que el oráculo de igualdad estricta rompe por diseño. Correr `python -m tests.carga.ejecutar_corpus` y actualizar el oráculo con los valores nuevos.
- [ ] 16.2 Confirmar sin regresión de tiempo/memoria frente a la última corrida validada (ver `openspec/changes/puerto-de-ingesta/tasks.md`, Fase 9, para los valores de referencia más recientes) — el campo nuevo es de costo marginal, pero el pico de memoria es parte del contrato y se revalida igual.
- [ ] 16.3 Regenerar y correr `tests/carga/ejecutar_corpus_10000.py`: mismo criterio, confirmar composición idéntica del corpus (únicos/duplicados/aprobados/episodios/cuarentenas) salvo por el campo nuevo, y ausencia de regresión a escala.
- [ ] 16.4 `pytest` completo del repositorio en verde.

## Pronóstico de carga de revisión

| Campo | Valor |
|---|---|
| Líneas estimadas | 550–680 |
| Riesgo de presupuesto 400 líneas | High |
| PRs encadenados recomendados | Yes |
| División sugerida | PR1 (unidad 1: dominio + parseo + reconciliación + Parquet, Fases 1-10) → PR2 (unidad 2: ORM + migración + Postgres, Fases 11-14) → PR3 (calibración + carga, Fases 15-16) |
| Delivery strategy | no especificada por el orquestador — se asume `ask-on-risk` |
| Chain strategy | pending — requiere elección del usuario |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Unidades de trabajo mapeadas a PRs

| Unidad | Objetivo | PR | Notas |
|---|---|---|---|
| 1 | Dominio (`PrecisionHora` + campos) + normalización + ECG + laboratorio + eco (parseo y reconciliación) + Parquet (Fases 1-10) | PR1 | Autónoma, se revierte sin pérdida de datos. Incluye las 3 compuertas de calibración en línea con su parser. |
| 2 | `Estudio` (ORM) + migración `0006` + escritor Postgres + integración extremo a extremo (Fases 11-14) | PR2 | Depende de PR1 (el campo de dominio debe existir antes). Único con costo de datos al revertir. |
| 3 | Cierre de calibración + regeneración y corrida de oráculos de carga (Fases 15-16) | PR3 | Depende de PR2 (necesita ambos destinos completos para regenerar oráculos válidos). |

Nota sobre el tamaño: la estimación (550-680 líneas) ya asume la división en 3 PRs — cada PR individual queda razonablemente por debajo del presupuesto de 400 líneas si se respeta esta división; combinarlos en un solo PR excede el presupuesto con alta probabilidad, sobre todo por el volumen de tests de calibración (compuertas estrictas campo por campo) y los oráculos regenerados.
