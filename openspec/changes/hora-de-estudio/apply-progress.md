# Progreso de aplicación: hora del estudio (PR1 — Fases 1 a 10)

Lote 1 (primer y único lote de este PR). No hay progreso previo que fusionar.

**Modo**: Strict TDD (RED → GREEN → REFACTOR), `pytest`.
**Delivery strategy**: `auto-chain`. **Chain strategy**: `stacked-to-main`.
**Alcance de este PR**: Fases 1–10 (dominio, normalización, ECG, laboratorio,
eco, cuarentena por hora ilegible, propagación a salida, Parquet). Fases
11–16 (ORM, migración, escritor Postgres, integración, cierre de
calibración, oráculos de carga) quedan para PR2/PR3, según el pronóstico de
carga de revisión de `tasks.md`.

## Resultado final de la suite

```
pytest -q
474 passed, 1 skipped in ~87s
```

El único `skipped` es preexistente y no relacionado con este cambio:
`tests/ingesta/test_fuente.py:217`, un test que requiere privilegio de
enlaces simbólicos no disponible en este entorno Windows.

**Nada quedó en rojo.** Ninguna compuerta de calibración fue ajustada para
tapar un fallo — donde una aserción calibrada no matcheaba el comportamiento
real, se corrigió el código de producción, nunca la expectativa del test
salvo cuando el propio diseño lo exigía explícitamente (task 5.2: invertir
una aserción que hoy pasaba en `adicionales["hora_extraccion"]` a "ya no
debe estar ahí" tras la promoción a campo tipado).

## Decisión de la Fase 2.1 (dejada abierta por las tareas)

**Pregunta**: ¿`"8:45"` sin cero a la izquierda se acepta o se rechaza?

**Decisión: rechazar.** `normalizar_hora_iso` (`reconciliacion/normalizacion.py`)
exige dos dígitos en la hora, vía un chequeo de ida y vuelta
(`datetime.strftime(formato) == candidato`) después de `strptime` (que por sí
solo es laxo con ceros a la izquierda y aceptaría `"8:45"` igual que
`"08:45"`).

**Por qué**: las muestras sintéticas calibradas contra el layout real (ver
`tests/fixtures/pdf_sintetico.py`) siempre usan dos dígitos — el ECG imprime
`08:30:00` en el header, el laboratorio imprime `Hora de Extraccion: 08:30`.
No hay evidencia de que el formato real alguna vez omita el cero. Dado el
principio explícito de "cero inferencia" que ya aplica `normalizar_fecha_iso`
(mismo módulo), es más seguro rechazar un formato no confirmado contra el
documento real que aceptarlo de más y arriesgar una hora mal interpretada
más adelante (p. ej. confundir "8" con "08" horas AM/PM en un layout futuro
que sí lo requiera). Si una muestra real futura demuestra que el layout usa
horas sin cero a la izquierda, este es el único lugar que hay que tocar.

## Los cuatro gotchas del diseño — cómo se cerraron

1. **Cobertura 1:1 del ECG (design.md, decisión 4).** El patrón de inventario
   de `ecg.hora_estudio` reutiliza literalmente el mismo patrón anclado de
   `ecg.fecha_estudio` (`\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2}`), nunca
   un `\d{2}:\d{2}:\d{2}` suelto. Demostrado con un test dedicado
   (`test_patron_de_hora_suelto_produce_cobertura_ambigua_contra_header_real`,
   `tests/reconciliacion/test_ecg_mortara.py`) que construye a mano los
   `HallazgoCobertura` de un patrón suelto contra un header con dos horas
   sueltas y confirma `COBERTURA_AMBIGUA` directamente vía `verificar_cobertura`
   — sin pasar por el reconciliador real, que ya usa el patrón anclado.

2. **`validador_asociacion` de laboratorio (design.md, decisión 4, "la parte
   más frágil").** `reconciliar_referencias` llamada sin `validador_asociacion`
   cae en `pagina.count(valor) == 1`. Reproducido con
   `test_hora_extraccion_sin_validador_asociacion_rechaza_documento_legitimo`
   (un `"08:30"` que aparece dos veces en la página produce `EVIDENCIA_AMBIGUA`
   incluso siendo un documento legítimo). Arreglado con `_asociacion_laboratorio`,
   anclada al rótulo `Hora(?:\s+de)?\s+Extracci[oó]n:`.
   **Desviación descubierta por TDD, no anticipada por el diseño**: pasar
   `validador_asociacion` en la MISMA llamada de `reconciliar_referencias` que
   resuelve `laboratorio.resultado` rompía esa ruta — `_comun.py` exige
   asociación válida para TODA referencia no exceptuada una vez que el
   parámetro deja de ser `None`, y `_asociacion_laboratorio` devuelve `False`
   para cualquier selector que no sea de hora. Se resolvió llamando
   `reconciliar_referencias` **dos veces**, cada una con el subconjunto de
   `documento.fuentes` que le corresponde (`dataclasses.replace`), sin tocar
   `_comun.py`.

3. **Schema explícito de Parquet (design.md, decisión 3).** `pa.Table.from_pylist`
   infiere el tipo de columna por lote; un lote compuesto enteramente por
   ecocardiogramas dejaba `hora_estudio` con tipo `null`. Se declaró
   `pa.schema` explícito para los cuatro datasets (`laboratorio`, `ecg`,
   `eco_medidas`, `eco_texto`), confirmado con
   `test_escribir_lote_solo_de_eco_declara_tipo_explicito_de_hora_estudio`.

4. **`precision_hora` no derivable del valor (design.md, decisión 3).**
   Confirmado con `test_precision_hora_distingue_valores_de_hora_byte_a_byte_identicos`:
   un laboratorio a las `08:45` (MINUTO) y un ECG a esa misma hora (SEGUNDO)
   persisten el mismo string `"08:45:00"` en Parquet; solo `precision_hora`
   los distingue.

## Invariantes verificados

- **Ausencia explícita nunca es un default**: el eco nunca declara
  `hora_estudio`/`id_campo` de hora; los defaults de dominio (`None`/`AUSENTE`)
  lo resuelven sin código nuevo. Aserción negativa explícita en
  `test_eco_emite_ausencia_explicita_nunca_un_default_de_medianoche` y en la
  compuerta de calibración (`resumen.hora_estudio != "00:00:00"`).
- **"No trae" ≠ "no se pudo leer"**: hora ilegible (`"25:99"`) va a cuarentena
  (`PARSEO_INCOMPLETO`) tanto en ECG como en laboratorio, nunca se publica
  como `precision_hora = AUSENTE`.
- **Sin inferencia**: `normalizar_hora_iso` solo acepta `%H:%M:%S`/`%H:%M`
  explícitos, cero corrección de formatos ambiguos.
- **Procedencia citable**: `ecg.hora_estudio` y `laboratorio.hora_extraccion`
  tienen su propia `ReferenciaCampo`, verificada contra el documento fuente
  con el mismo criterio de discrepancia/ambigüedad que el resto de los campos.

## Desviaciones del orden literal de fases (documentadas, no ocultadas)

1. **Whitelist adelantada.** `REFERENCIAS_PERMITIDAS["ecg.hora_estudio"]` y
   `REFERENCIAS_PERMITIDAS["laboratorio.hora_extraccion"]` se agregaron en el
   commit de Fase 3/1 (antes de lo que sugiere el orden literal de
   `tasks.md`, que las ubica en Fase 4.3/6.5). Razón: `ReferenciaCampo.__post_init__`
   valida contra la whitelist en el momento de CONSTRUCCIÓN, dentro del
   parser — sin la entrada, el parseo mismo del ECG/laboratorio rompía antes
   de llegar a reconciliación.
2. **Fases 3+4 y 5+6 se verificaron en verde juntas.** Las compuertas de
   calibración (`tests/calibracion/`) invocan reconciliación end-to-end
   (`evaluar_ecg`, `evaluar_laboratorio`); su RED de Fase 3.1/5.1 no se
   estabiliza en verde hasta que la reconciliación de la Fase 4/6
   correspondiente también está completa. Cada par se implementó y verificó
   como una unidad atómica antes de cerrar el commit, tal como indica el
   propio `tasks.md` ("las compuertas... van en la misma unidad de commit
   que ese parser").
3. **Fase 7 (eco) y parte de la Fase 8 (ECG) son RED que pasan sin cambio de
   código.** Los defaults de la Fase 1 y el diseño de `_parsear_fecha` de la
   Fase 3 (que devuelve `(fecha, hora, precision)` en una sola función) ya
   entregaban el comportamiento correcto antes de escribir esos tests.
   Documentado explícitamente en `tasks.md` como excepción al ciclo RED
   estricto — la razón es arquitectónica (el trabajo ya estaba hecho por una
   fase anterior), no un test mal escrito. Se agregaron igual como red de
   seguridad explícita.
4. **Tests existentes ajustados por la nueva `ReferenciaCampo` de hora.**
   Agregar `ecg.hora_estudio`/`laboratorio.hora_extraccion` a `fuentes` altera
   el contenido (y a veces el orden) de `documento.fuentes`. Se actualizaron:
   - `tests/reconciliacion/test_inventario.py::test_inventario_ecg_aprueba_headers_y_medidas_con_destino_unico`
     (agregada la fuente de hora faltante).
   - `tests/parseo/test_laboratorio_general.py` (3 asserts que iteraban
     `documento.fuentes` sin filtrar por `id_campo` ahora filtran
     explícitamente `"laboratorio.resultado"`).
   - `tests/parseo/test_laboratorio_general.py::test_header_real_con_espacio_antes_de_dos_puntos_y_etiquetas_alternativas`
     invertido de "hora_extraccion vive en adicionales" a "ya no vive ahí"
     (task 5.2, explícitamente pedido por el diseño).

## Riesgos / seguimiento para PR2

- Fase 5.5: no hay muestra real (ni sintética distinta) de un laboratorio SIN
  `Hora de Extracción:` en el header — el caso de ausencia se probó contra el
  header sintético existente con la línea removida manualmente, no contra una
  variante de layout real confirmada. Si aparece una muestra real así en el
  futuro, recalibrar contra ella.
- PR2 (Fases 11–14, ORM + migración + Postgres) depende de que el campo de
  dominio de este PR exista — ya existe y está probado. PR2 puede empezar de
  inmediato.
- PR3 (Fases 15–16) necesita ambos destinos completos (SQL de PR2 + Parquet
  de este PR) antes de regenerar los oráculos de carga — el schema de
  Parquet ya cambió acá, así que esos oráculos rompen por diseño y deben
  regenerarse recién quede cerrado PR2.

## Commits de este lote

1. `2b49e73` — `feat(dominio): agrega PrecisionHora y hora_estudio a los modelos` (Fase 1)
2. `a3528a9` — `feat(reconciliacion): agrega normalizar_hora_iso sin inferencia` (Fase 2)
3. `6986c74` — `feat(ecg): conserva hora del estudio con procedencia anclada al timestamp` (Fases 3+4)
4. `e8ababc` — `feat(laboratorio): promueve hora_extraccion a campo tipado con evidencia anclada` (Fases 5+6)
5. `5cb4654` — `test(eco): fija ausencia explicita de hora y cuarentena por hora ilegible` (Fases 7+8)
6. `ac6517b` — `feat(salida): propaga hora_estudio y precision_hora al registro anonimizado` (Fase 9)
7. `804cc28` — `feat(parquet): declara schema explicito para hora_estudio/precision_hora` (Fase 10)

Ningún commit fue pusheado; no se abrió PR (por instrucción explícita del
encargo).

## Estado de tareas

Todas las tareas de Fases 1 a 10 marcadas `[x]` en `openspec/changes/hora-de-estudio/tasks.md`,
con notas inline documentando desviaciones puntuales. Fases 11–16 quedan
`[ ]`, sin tocar — fuera de alcance de este lote.

## Lote 2 (PR2) — persistencia del momento del estudio

Fases 11 a 14 completas. `pytest` completo: 486 pasados, 1 omitido (skip
preexistente por privilegios de symlink en Windows).

### Qué se hizo

- **Fase 11**: clase `Estudio` en `salida/modelos_orm.py`
  (`id_estudio`, `id_episodio`, `tipo_documento`, `fecha_estudio`,
  `hora_estudio`, `precision_hora`) y FK `id_estudio` nullable e indexada en
  `MedicionEcg`, `ResultadoLaboratorio` y `MedicionEco`. Tests nuevos en
  `tests/salida/test_modelos_orm.py` (archivo nuevo).
- **Fase 12**: `migrations/versions/0006_estudio_y_hora.py`, encadenada sobre
  `0005_tamano_y_tope_cuarentena`. Los tres `add_column` con FK van dentro de
  `op.batch_alter_table` porque SQLite no soporta `ALTER TABLE` con FK y la
  suite corre contra SQLite. `downgrade` cubierto por test, y también el ciclo
  `upgrade`/`downgrade`/`upgrade`.
- **Fase 13**: `escribir_registro` inserta la fila de `estudio`, hace `flush`
  para obtener el `id_estudio` y lo propaga a las tres escrituras de medición.
- **Fase 14**: `tests/integracion/test_momento_estudio_ambos_destinos.py`
  recorre los tres tipos de documento y verifica que hora y precisión llegan
  idénticas a SQL y a Parquet, incluida la ausencia del ecocardiograma.

### Desvío respecto del plan, deliberado

El diseño proponía `escribir_estudio(registro) -> int` como método propio,
llamado desde `escribir_registro` antes del despacho por tipo. Se implementó
**dentro de una única sesión** en lugar de como método independiente, porque
cada `_escribir_*` abría su propia sesión: con un método separado, la fila de
`estudio` habría commiteado antes que las mediciones y un fallo posterior
dejaría un `estudio` huérfano sin mediciones, indistinguible de un documento
legítimamente vacío. Los tres `_escribir_*` ahora reciben la sesión y el
`id_estudio` en lugar de abrir sesión propia.

Esto **no** resuelve la idempotencia de `escribir_registro`: reprocesar el
mismo documento sigue creando filas duplicadas, ahora también en `estudio`.
Queda fuera de alcance por decisión del diseño y está anotado en el docstring
del método.

### Dos tests que fallaron por fixture propia, no por el código

`ContenidoEcg` y `ContenidoEco` exigen todos sus campos posicionales; las
fixtures iniciales los omitían. Se corrigieron las fixtures, no el código de
producción.

### Qué queda

- Fases 15 y 16 (PR3): cierre de compuertas de calibración y regeneración más
  corrida de los oráculos de carga de 1.000 y 10.000 PDFs. Los oráculos rompen
  **por diseño**, porque cambia el schema de Parquet.

