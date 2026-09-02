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

- [x] 1.1 RED: en `tests/dominio/test_modelos.py` (o archivo equivalente existente), test que instancia `DocumentoParseado` y `RegistroAnonimizado` con `hora_estudio: time | None` y `precision_hora: PrecisionHora`, y falla porque el dataclass todavía no acepta esos campos.
- [x] 1.2 RED: test que construye `DocumentoParseado` con `fecha_estudio` y `hora_estudio` ambos presentes y verifica que `fecha_estudio` sigue siendo `date` sin alteración (Requirement: "Campo de hora opcional, separado de la fecha", spec `momento-del-estudio`).
- [x] 1.3 GREEN: crear `src/anonimizacion/dominio/precision_hora.py` — `class PrecisionHora(str, Enum)` con `AUSENTE`, `MINUTO`, `SEGUNDO`.
- [x] 1.4 GREEN: en `dominio/modelos.py`, agregar `hora_estudio: time | None = None` y `precision_hora: PrecisionHora = PrecisionHora.AUSENTE` a `DocumentoParseado` y a `RegistroAnonimizado` (defaults para no romper construcciones existentes en tests de otras fases del pipeline).
- [x] 1.5 REFACTOR: revisar que ningún otro sitio del dominio asuma que estos dos dataclasses solo tienen los campos previos (p. ej. destructuring posicional); ajustar si aparece. Confirmado: los nuevos campos van al final con defaults, todas las construcciones posicionales existentes (p. ej. `DocumentoParseado(TipoDocumento.ECG, 1, IdentidadCruda(...), date(...), ContenidoEcg(...), fuentes=fuentes)`) siguen funcionando sin cambios — verificado con la suite completa en verde.

## Fase 2: normalización de hora sin inferencia

- [x] 2.1 RED: en `tests/reconciliacion/test_normalizacion.py`, tabla de casos para una función `normalizar_hora_iso` que todavía no existe: acepta `"08:45:00"` → `"08:45:00"`, acepta `"08:45"` → `"08:45"`, rechaza `"8:45"` (sin cero relativo — confirmar contra el formato real del documento antes de decidir si se acepta; si el layout real trae hora sin cero relativo, agregarlo como caso aceptado en vez de rechazado), rechaza `"25:00"`, rechaza cualquier string no numérico. Decisión tomada: **rechazar** `"8:45"` — las muestras sintéticas calibradas (ECG `HH:MM:SS`, laboratorio `Hora de Extracción: HH:MM`) siempre usan dos dígitos; ver docstring de `normalizar_hora_iso`.
- [x] 2.2 GREEN: `normalizar_hora_iso(valor: str) -> tuple[str, PrecisionHora]` en `reconciliacion/normalizacion.py`, espejo de `normalizar_fecha_iso`: prueba `%H:%M:%S` (devuelve `SEGUNDO`) y `%H:%M` (devuelve `MINUTO`) en ese orden, levanta `ValueError` si ninguno matchea. Cero inferencia, cero corrección de formatos ambiguos. Chequeo de ida y vuelta (`strftime(formato) == candidato`) para rechazar horas sin cero a la izquierda, ya que `strptime` por sí solo es laxo con eso.
- [x] 2.3 REFACTOR: confirmar que la firma no colisiona con el patrón existente de `normalizar_fecha_iso` (misma convención de excepción, mismo estilo de docstring). Confirmado.

## Fase 3: ECG — dejar de truncar la hora

- [x] 3.1 RED: en `tests/calibracion/test_compuerta_ecg.py`, agregar la aserción de hora contra la muestra real: un ECG con header `DD-MON-YYYY HH:MM:SS` produce `hora_estudio` con precisión de segundo, valor exacto verificado campo por campo (compuerta estricta, no aproximada). Este RED se agrega **en el mismo work unit que el parser** (Fase 3), nunca después. Nota: este RED solo se estabiliza en verde al completar Fase 4 (la compuerta invoca reconciliación end-to-end); documentado como acoplamiento inherente en `apply-progress.md`.
- [x] 3.2 RED: en `tests/parseo/test_ecg_mortara.py`, test unitario que falla si `_parsear_fecha` vuelve a truncar: dado un header con hora, el `DocumentoParseado` resultante expone `hora_estudio` no nulo con precisión `SEGUNDO`.
- [x] 3.3 GREEN: modificar `_parsear_fecha` en `parseo/ecg_mortara.py:234` — de devolver solo `date` a devolver `(date, time)`, reutilizando la porción horaria ya capturada en `header["fecha"]` (patrón `_CAMPOS_HEADER["fecha"]`, línea 93, ya matchea `HH:MM:SS` completo). Usar `normalizar_hora_iso` (Fase 2) sobre la porción horaria para obtener `hora_estudio` y `precision_hora`.
- [x] 3.4 GREEN: agregar `ReferenciaCampo("ecg.hora_estudio", 1, "ecg.hora_estudio")` a `fuentes` en `ParseadorEcgMortara.parsear`. Nota: la entrada en `REFERENCIAS_PERMITIDAS` (task 4.3) tuvo que adelantarse a esta tarea — `ReferenciaCampo.__post_init__` valida contra la whitelist en el momento de construcción, así que sin la entrada el parseo mismo rompía. Documentado como desviación del orden literal de fases.
- [x] 3.5 REFACTOR: revisar que `ContenidoEcg` no necesite el campo (la hora vive en `DocumentoParseado`, no en el contenido tipado por tipo de documento) y que `adicionales` no siga conteniendo la porción horaria del header por duplicado. Confirmado: `header["fecha"]` sigue excluido de `adicionales` (ya estaba en `_CAMPOS_HEADER_EXCLUIDOS_DE_ADICIONALES`).

## Fase 4: ECG — procedencia anclada al timestamp completo (gotcha 1)

- [x] 4.1 RED: en `tests/reconciliacion/test_ecg_mortara.py`, test que agrega el `id_campo` `"ecg.hora_estudio"` al whitelist sin patrón de inventario correspondiente y confirma `COBERTURA_INCOMPLETA` — fija el comportamiento antes de agregar el patrón.
- [x] 4.2 RED: test que agrega un patrón de inventario **suelto** (`\d{2}:\d{2}:\d{2}` sin anclar al timestamp completo) contra un header ECG real y confirma que produce `COBERTURA_AMBIGUA` porque también matchea otra hora suelta del mismo documento (p. ej. una hora de impresión). Este test documenta el gotcha del diseño de forma aislada, construyendo los `HallazgoCobertura` a mano contra `verificar_cobertura` directamente (sin pasar por `ReconciliadorEcgMortara`, que ya usa el patrón anclado).
- [x] 4.3 GREEN: en `dominio/referencias.py`, agregar `"ecg.hora_estudio": frozenset({"ecg.hora_estudio"})` a `REFERENCIAS_PERMITIDAS`.
- [x] 4.4 GREEN: en `reconciliacion/ecg_mortara.py`, agregar a `_PATRONES_INVENTARIO` un patrón anclado al timestamp **completo** (reutilizando el mismo grupo que `ecg.fecha_estudio`, línea 21: `\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2}`) que capture selectivamente la porción horaria, de forma que no colisione con el patrón de institución (línea 94, que también matchea `\d{2}:\d{2}:\d{2}\s+.+`). Agregar rama correspondiente en `_asociacion_ecg` que valide el valor de hora contra ese mismo ancla.
- [x] 4.5 GREEN: incluir `("ecg.hora_estudio", 0): <hora formateada HH:MM:SS>` en el diccionario `valores` de `ReconciliadorEcgMortara.reconciliar`.
- [x] 4.6 REFACTOR: correr `verificar_cobertura` directo (test dedicado) confirmando que el 1:1 se sostiene con el `id_campo` nuevo, sin `COBERTURA_AMBIGUA` ni `COBERTURA_INCOMPLETA` contra un documento real (sintético). `tests/reconciliacion/test_ecg_mortara.py::test_reconcilia_hora_estudio_anclada_al_timestamp_completo`.

## Fase 5: laboratorio — promover `hora_extraccion` a campo tipado

- [x] 5.1 RED: en `tests/calibracion/test_compuerta_laboratorio.py`, agregar la aserción de hora contra la muestra real: un laboratorio con `Hora de Extracción: HH:MM` produce `hora_estudio` con precisión `MINUTO`, valor exacto. En el mismo work unit que este parser, nunca después. Igual que Fase 3, este RED solo se estabiliza en verde al completar Fase 6 (reconciliación end-to-end).
- [x] 5.2 RED: en `tests/parseo/test_laboratorio_general.py`, test que confirma que `hora_extraccion` **ya no aparece** en `documento.adicionales` una vez promovido. Se actualizó también el test existente que aserta el valor crudo en `adicionales` (invertido a "no debe estar ahí" tras el GREEN) y se agregó un caso de ausencia (sin `Hora de Extracción:` en el header → `precision_hora = AUSENTE`).
- [x] 5.3 GREEN: en `parseo/laboratorio_general.py`, extraer `header["hora_extraccion"]` y normalizarlo con `normalizar_hora_iso` para poblar `hora_estudio`/`precision_hora` del `DocumentoParseado`; excluido de `adicionales`.
- [x] 5.4 GREEN: agregar `ReferenciaCampo("laboratorio.hora_extraccion", <página del header>, "laboratorio.hora_extraccion")` a `fuentes`. Nota: esto reordena `documento.fuentes` (la referencia de hora queda primero); se actualizaron 3 tests de parseo existentes que iteraban `documento.fuentes` sin filtrar por `id_campo` para que filtren explícitamente `"laboratorio.resultado"`.
- [x] 5.5 REFACTOR: confirmado con test dedicado (`test_hora_extraccion_ausente_produce_precision_ausente_sin_romper_el_parseo`) usando el header sintético existente sin la línea de `Hora Extracción:` — no hay muestra real distinta para calibrar esta variante; documentado como suposición hasta una calibración futura.

## Fase 6: laboratorio — `validador_asociacion` anclado (gotcha 2, la parte frágil)

- [x] 6.1 RED: en `tests/reconciliacion/test_laboratorio_general.py`, test que llama `reconciliar_referencias` directamente (sin `validador_asociacion`) con una página donde `"08:30"` aparece dos veces (el rótulo real + una coincidencia no relacionada) y confirma `EVIDENCIA_AMBIGUA` — reproduce el bug documentado en el diseño antes de arreglarlo.
- [x] 6.2 RED: test que confirma que, con `_asociacion_laboratorio` aplicado, el mismo documento reconcilia sin error.
- [x] 6.3 GREEN: en `reconciliacion/laboratorio_general.py`, `_asociacion_laboratorio` busca el rótulo `Hora(?:\s+de)?\s+Extracci[oó]n:` y valida que el valor esperado aparece inmediatamente después.
- [x] 6.4 GREEN: `ReconciliadorLaboratorioGeneral.reconciliar` ahora llama `reconciliar_referencias` **dos veces**: una para el resto de `fuentes` (sin `validador_asociacion`, ruta existente de `laboratorio.resultado` intacta) y otra solo para `laboratorio.hora_extraccion` con `validador_asociacion=_asociacion_laboratorio`. Desviación necesaria descubierta por TDD: pasar el validador en una única llamada global rompía `laboratorio.resultado`, porque `_comun.py::reconciliar_referencias` exige asociación válida para TODA referencia no exceptuada una vez que el parámetro no es `None` — partir por subconjunto de `fuentes` (vía `dataclasses.replace`) es la única forma de aislar el efecto al selector de hora sin tocar `_comun.py`.
- [x] 6.5 GREEN: `"laboratorio.hora_extraccion"` en `REFERENCIAS_PERMITIDAS` (adelantado a Fase 3/5 por la razón de construcción ya documentada) y patrón de inventario anclado al mismo rótulo en `ReconciliadorLaboratorioGeneral.inventariar`/`_hallazgos_hora_extraccion`.
- [x] 6.6 REFACTOR: `test_reconciliador_laboratorio_reconcilia_hora_extraccion_end_to_end` confirma el 1:1 sostenido contra un documento sintético; el rótulo `Hora(?:\s+de)?\s+Extracci[oó]n:` no matchea ninguna columna de resultados existente en los fixtures (columnas son `Pruebas`/`Resultado`/`Unidades`/`Valores de Referencia`, sin la palabra "hora").

## Fase 7: eco — ausencia explícita, nunca un default

- [x] 7.1 RED: en `tests/calibracion/test_compuerta_ecocardiograma.py`, agregar la aserción **negativa**: un eco parseado produce `precision_hora == PrecisionHora.AUSENTE` y `hora_estudio is None`, y el test falla explícitamente si en algún momento aparece `time(0, 0)` o cualquier hora no-`None`. Nota: este test pasa sin ningún cambio de código porque los defaults de la Fase 1 ya entregan el comportamiento correcto — documentado como excepción deliberada al ciclo RED estricto (ver apply-progress.md).
- [x] 7.2 RED: en `tests/parseo/test_eco_doppler.py`, test que confirma que `ParseadorEcoDoppler.parsear` nunca agrega `ReferenciaCampo` de hora ni `id_campo` de hora a `fuentes`. Misma nota que 7.1: pasa sin cambio de código.
- [x] 7.3 GREEN: en `parseo/eco_doppler.py`, comentario explícito en `parsear` (antes de construir `ContenidoEco`) documentando que `hora_estudio`/`precision_hora` quedan en los defaults de la Fase 1 y citando el Requirement de la spec — sin cambio de comportamiento.
- [x] 7.4 REFACTOR: confirmado — suite completa de eco (`test_eco_doppler.py`, `test_compuerta_ecocardiograma.py`, `reconciliacion/test_eco_doppler.py`) en verde sin cambios adicionales.

## Fase 8: hora ilegible va a cuarentena, no a ausencia silenciosa

- [x] 8.1 RED: en `tests/parseo/test_ecg_mortara.py` y `tests/parseo/test_laboratorio_general.py`, test con un valor de hora presente pero con formato irreconocible (`"25:99"`) — confirma cuarentena (`PARSEO_INCOMPLETO`). El caso de laboratorio (`test_hora_extraccion_ilegible_va_a_cuarentena_no_a_ausencia_silenciosa`, Fase 5) es un RED genuino porque `_parsear_hora_extraccion` no existía. El caso de ECG (`test_hora_estudio_ilegible_va_a_cuarentena_no_a_ausencia_silenciosa`) pasa sin cambio adicional: el `try/except ValueError` que envuelve `_parsear_fecha` (Fase 3) ya cubre la porción de hora porque `_parsear_fecha` devuelve `(fecha, hora, precision)` en una sola función — documentado como consecuencia de esa decisión de diseño, no como gap.
- [x] 8.2 GREEN: `parseo/ecg_mortara.py` ya lo resolvía en Fase 3 (mismo `try/except` de `_parsear_fecha`); `parseo/laboratorio_general.py` agrega su propio `try/except ValueError` alrededor de `_parsear_hora_extraccion` en Fase 5, mismo patrón (`ErrorParseo(codigo=PARSEO_INCOMPLETO, etapa=_ETAPA)`).
- [x] 8.3 REFACTOR: confirmado — ninguno de los dos `except` propaga el valor crudo de hora, solo el código de error tipado.

## Fase 9: propagación a la salida (`salida/`)

- [x] 9.1 RED: en `tests/salida/test_constructor_registro.py`, test que confirma que `construir_registro` propaga `hora_estudio` y `precision_hora` del `DocumentoParseado` al `RegistroAnonimizado` sin transformarlos, más un test de ausencia (eco sin hora no recibe default).
- [x] 9.2 GREEN: `RegistroAnonimizado` ya tenía los campos (Fase 1); se agregó la propagación en `construir_registro` (`salida/constructor_registro.py`, construcción final del `RegistroAnonimizado`).
- [x] 9.3 REFACTOR: confirmado — `grep hora salida/modelos_salida.py` sin resultados, ningún payload `ContenidoXSalida` necesita el campo.

## Fase 10: Parquet — schema explícito (gotcha 4)

- [x] 10.1 RED: en `tests/salida/destinos/test_parquet.py`, test que escribe un lote **compuesto enteramente por ecocardiogramas** y confirma que la columna `hora_estudio` en el Parquet resultante NO queda con tipo `null` inferido — debe tener un tipo string explícito. Falló contra el código sin schema (`KeyError`/tipo `null` inferido) antes del GREEN.
- [x] 10.2 GREEN: `destinos/parquet.py` declara `pa.schema` explícito (`_SCHEMA_LABORATORIO`, `_SCHEMA_ECG`, `_SCHEMA_ECO_MEDIDAS`, `_SCHEMA_ECO_TEXTO`) con `hora_estudio`/`precision_hora` como `pa.string()`, pasado a `pa.Table.from_pylist(filas, schema=...)` en los cuatro datasets.
- [x] 10.3 GREEN: `hora_estudio`/`precision_hora` agregados a los diccionarios de fila en los cuatro builders (`_filas_laboratorio`, `_filas_ecg`, `_filas_eco_medidas`, `_filas_eco_texto`) — el eco también propaga `precision_hora=AUSENTE`.
- [x] 10.4 REFACTOR: `test_dataset_combinado_ecg_y_eco_no_choca_por_tipo_de_columna_hora` y `test_precision_hora_distingue_valores_de_hora_byte_a_byte_identicos` confirman lectura correcta con y sin valores no nulos, y que `precision_hora` distingue una hora de laboratorio (MINUTO) de una hora de ECG (SEGUNDO) byte-a-byte idénticas en `hora_estudio`.

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
