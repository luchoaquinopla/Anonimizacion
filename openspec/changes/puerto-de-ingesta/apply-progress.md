# Progreso de aplicación: puerto de ingesta

## Lote 1 (PR1) — Fases 1, 2 y 3

Estado: **completo**. `pytest` completo: 433 passed, 1 skipped (skip preexistente,
no relacionado: el entorno Windows no permite crear symlinks sin privilegio elevado
en `test_inventariador_omite_enlace_simbolico_que_resuelve_fuera_de_la_raiz`).

### Hecho

- **Fase 1** — `Protocol FuenteDeArtefactos` (`listar()`/`abrir()`) declarado en
  `src/anonimizacion/ingesta/fuente.py`, `@runtime_checkable`, simétrico a
  `DestinoEscritura`/`DestinoCuarentena` (`pipeline/ejecutor.py` L83/L98).
- **Fase 2** — `FuenteLocal` (nuevo, parcial) con `listar()` que valida raíz
  autorizada y existencia de directorio de forma ANSIOSA antes de retornar el
  generador interno (`_listar_generador`). Confirmado que la validación dispara
  `PermissionError`/`FileNotFoundError` sin iterar el resultado.
- **Fase 3** — `Protocol RegistroDeHuellas` (`es_nueva(sha256) -> bool`) +
  `HuellasEnMemoria` (set en memoria). `FuenteLocal.listar()` ya usa
  `huellas: RegistroDeHuellas` para omitir contenido duplicado dentro de una
  misma operación de listado.
- `FuenteArtefacto` e `InventariadorDocumentos` quedan **intactos** y siguen
  siendo usados por los consumidores actuales (`scripts/procesar_carpeta.py`,
  `tests/fixtures/corpus_piloto.py`) — no se tocan hasta la Fase 4 (PR2).

### Desvíos respecto del plan (documentados, no ocultos)

1. **Tarea 1.1**: la redacción literal decía "`FuenteLocal` debe satisfacer
   `FuenteDeArtefactos`". Eso es imposible de probar en este PR sin adelantar
   trabajo de la Fase 5: `abrir()` en `FuenteLocal` no existe todavía (llega
   con la revalidación de `uri` y verificación de sha256 en PR2). Probarlo
   ahora habría dado un falso rechazo del contrato, no un RED legítimo. Se
   probó el `Protocol` contra dos dobles mínimos definidos en el propio test
   (`_FuenteDobleCompleta`, `_FuenteDobleIncompleta`) — uno conforme, uno sin
   `abrir()`. Cuando la Fase 5 complete `FuenteLocal.abrir()`, vale la pena
   agregar un tercer test que sí verifique `isinstance(FuenteLocal(...),
   FuenteDeArtefactos)` contra la implementación real.
2. **`FuenteLocal` es un adaptador parcial en este PR**, no el reemplazo
   unificado descrito en la Fase 4.4. Tiene `raices`, `directorio`, `huellas`
   y una implementación completa de `listar()` (recorrido recursivo, filtro
   por extensión, hasheo por bloques reutilizando el mismo patrón de
   `InventariadorDocumentos._calcular_huella`, dedup vía `RegistroDeHuellas`).
   Le faltan a propósito: `tope_bytes`, `Protocol SumideroCuarentena`,
   cuarentena por sobretamaño y `abrir()`. Esos llegan en la Fase 4-5 (PR2) sin
   necesidad de reescribir lo ya construido — solo se extiende
   `_listar_generador` con la rama de cuarentena y se agrega `abrir()`.
3. No se creó `src/anonimizacion/ingesta/huellas_corrida.py` ni
   `HuellasDeCorrida`: decisión ya resuelta al inicio de `tasks.md` (sin
   consumidor productivo en este cambio, se implementa junto con el
   despachador que asigne `corrida_id`).

### Qué queda (PR2 en adelante, fuera de este lote)

- Fase 4: extender `FuenteLocal` con `tope_bytes`, `SumideroCuarentena`,
  cuarentena por sobretamaño (`ARTEFACTO_SOBRETAMANO`, `EtapaDocumento.INGESTA`,
  `tamano_bytes`/`tope_bytes` en `ErrorDocumento`); eliminar
  `FuenteArtefacto`/`InventariadorDocumentos`.
- Fase 5: `abrir()` con revalidación de raíz y verificación de sha256.
- Fase 6-7: `extraer_texto_de_flujo` + rewiring de `ejecutor.py`/`tareas.py`.
- Fase 8-9: migración de consumidores + ensayos de carga (1.000 y 10.000 PDFs)
  + suite completa.

## Commits de este lote

Ver `git log` en la rama `feat/puerto-ingesta-protocolo`: unidad de trabajo
única (Protocol + trampa del generador + costura de dedup), tests incluidos
en el mismo commit que el comportamiento que verifican.

## Lote 2 (PR2) — Fases 4 y 5

Rama: `feat/puerto-ingesta-fuente-local`, apilada sobre
`feat/puerto-ingesta-protocolo` (PR1, en revisión).

Estado: **completo**. `pytest` completo: 437 passed, 1 skipped (mismo skip
preexistente de PR1, no relacionado: symlinks sin privilegio elevado en
Windows).

### Hecho

- **Fase 4** — `FuenteLocal.listar()` ahora aplica el tope de tamaño
  (`tope_bytes`, default 50 MiB provisional — ver "Preguntas abiertas" de
  design.md) y aparta a **cuarentena** el archivo que lo supera, en vez de
  lanzar `ValueError` y abortar el lote: se agrega
  `CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO`, `EtapaDocumento.INGESTA` y
  los campos opcionales `tamano_bytes`/`tope_bytes` en `ErrorDocumento`
  (`dominio/errores.py`). `id_documento` del artefacto rechazado es el
  sha256 de la RUTA (no del contenido, que nunca se lee) porque el nombre de
  archivo puede llevar PII. La iteración **continúa** tras un sobretamaño:
  el resto de los archivos válidos del directorio se siguen listando. Se
  agrega `Protocol SumideroCuarentena` propio en `ingesta/fuente.py`
  (`registrar(error)`) — `ingesta` sigue sin importar `pipeline`;
  `EscritorCuarentena` lo satisface por tipado estructural.
- **Fase 5** — `FuenteLocal.abrir(artefacto) -> BinaryIO`: revalida la `uri`
  contra `raices` (rechaza con `PermissionError` si está fuera — simula una
  cola envenenada, ya que la `uri` viaja en el mensaje de Celery y hasta
  ahora nadie la revalidaba del lado del worker) y verifica que el sha256
  del contenido real coincida con `artefacto.sha256` antes de entregar el
  flujo (`ValueError` explícito si no coincide). Contrato de ciclo de vida
  documentado en el docstring: `abrir()` retorna un `BinaryIO` fresco e
  independiente; el LLAMADOR lo cierra con `with` (un objeto de archivo ya
  es context manager).
- **Asimetría preservada**: ruta fuera de raíces autorizadas en `listar()`
  sigue siendo `PermissionError` (falla dura, detiene la iteración) — no se
  convirtió en cuarentena. Es deliberado (design.md, Decisión 5): indica una
  configuración de seguridad incorrecta, no un documento individual
  defectuoso.
- **REFACTOR (4.5)** — se eliminaron `FuenteArtefacto` e
  `InventariadorDocumentos` de `ingesta/fuente.py`, junto con su
  duplicación de `_calcular_huella`/`_esta_dentro_de_raiz`. Se actualizó el
  docstring del módulo para reflejar que `FuenteLocal` es ahora el único
  adaptador.
- **Deuda de PR1 saldada** — el test de contrato del `Protocol
  FuenteDeArtefactos` ahora también corre contra `FuenteLocal` real
  (`test_protocolo_fuente_de_artefactos_acepta_fuente_local_real`), no solo
  contra los dobles mínimos: `abrir()` ya existe, así que el falso rechazo
  que motivó la desviación de PR1 ya no aplica. Los tests contra dobles se
  conservan porque siguen probando el rechazo estructural de un adaptador
  incompleto (algo que la implementación real no puede ejercitar).

### Adelanto de la Fase 8 (fuera del alcance formal de este lote)

Eliminar `FuenteArtefacto`/`InventariadorDocumentos` en 4.5 rompía sus dos
consumidores productivos. Para no dejar la suite en rojo (regla no
negociable de TDD estricto), se migraron ambos ya en este lote, **antes**
de lo previsto en el plan (la migración formal es la Fase 8, PR4):

- `scripts/procesar_carpeta.py` — `FuenteArtefacto(args.entrada).listar()`
  (retornaba `list`) pasa a
  `list(FuenteLocal(raices=(args.entrada,), directorio=args.entrada,
  cuarentena=cuarentena).listar())`, reutilizando el `EscritorCuarentena`
  que el script ya construye para el pipeline. Se conserva el guardia
  `if not artefactos`.
- `tests/fixtures/corpus_piloto.py:143` —
  `InventariadorDocumentos((directorio,), 10 MiB).inventariar(entrada)`
  pasa a `tuple(FuenteLocal(raices=(directorio,), directorio=entrada,
  tope_bytes=10*1024*1024, huellas=HuellasEnMemoria(),
  cuarentena=_CuarentenaMemoria()).listar())` — exactamente la firma que
  design.md ya proponía para esta migración. `_CuarentenaMemoria()` es una
  instancia dedicada al inventario, distinta de la que usa el ejecutor del
  pipeline para errores de procesamiento; no hay colisión porque ningún
  caso del corpus piloto supera 10 MiB (documentado en design.md).

**Qué queda todavía para la Fase 8 formal (PR4)**, y por qué no se adelantó:

- 8.3 — test de payload de cola (`{id_documento, uri, sha256}` exacto) en
  `tests/trabajadores/`: no se tocó nada del camino de despacho a cola en
  este lote (eso es Fase 6-7, PR3), así que no hay nada nuevo que ese test
  deba cubrir todavía.
- Ninguna prueba dedicada nueva se agregó para la migración de
  `procesar_carpeta.py`/`corpus_piloto.py` en sí misma (es un script manual
  y un fixture de corpus, no código de producción con tests unitarios
  propios) — la cobertura de que `FuenteLocal` se comporta bien ya vive en
  `tests/ingesta/test_fuente.py`; la migración se valida indirectamente
  porque `tests/carga/` y el corpus piloto siguen pasando con el nuevo
  wiring.
- Los ensayos de carga de 1.000 y 10.000 PDFs (9.1, 9.2) **no se
  re-ejecutaron a propósito** en este lote — no cambia nada del camino de
  hasheo/dedup que ejercitan (`tope_bytes` sigue en 10 MiB, `HuellasEnMemoria`
  sigue siendo la misma implementación); design.md ya anticipa que
  corresponde re-correrlos como parte de la Fase 9, no de esta migración
  anticipada. `pytest` completo (incluida la suite de `tests/carga/` que
  corre por default) sí pasó completo en este lote.

### Qué queda (PR3 en adelante, fuera de este lote)

- Fase 6: `extraer_texto_de_flujo` sobre `BytesIO`, `extraer_texto(ruta)`
  como envoltorio delgado.
- Fase 7: rewiring de `ejecutor.py` (parámetro `fuente`) y
  `tareas.py:41` `configurar_ejecutor` (fábrica que construye e inyecta
  `FuenteLocal`).
- Fase 8: 8.3 (test de payload de cola) — 8.1 y 8.2 quedaron adelantados en
  este lote, ver arriba.
- Fase 9: ensayos de carga (1.000 y 10.000 PDFs) contra el wiring final del
  pipeline (Fase 7), y `pytest` completo en verde una vez más.

## Commits de este lote

1. `feat(dominio): agrega ARTEFACTO_SOBRETAMANO y EtapaDocumento.INGESTA` —
   vocabulario de dominio, prerequisito aislado antes de tocar `fuente.py`.
2. `feat(ingesta): FuenteLocal unificado con tope, cuarentena y abrir()` —
   `FuenteLocal` completo (tope+cuarentena+`abrir()`), eliminación de
   `FuenteArtefacto`/`InventariadorDocumentos`, migración mínima de sus dos
   consumidores y tests (RED+GREEN) en el mismo commit que el comportamiento
   que verifican.

## Lote 3 (PR2, corrección) — persistencia real de `tamano_bytes`/`tope_bytes`

Rama: `feat/puerto-ingesta-fuente-local` (misma rama de PR2).

Estado: **completo**. `pytest` completo: 438 passed, 1 skipped (mismo skip
preexistente de symlinks en Windows).

### Defecto encontrado

La spec de `puerto-de-ingesta` exige que el motivo de cuarentena por
sobretamaño incluya el tamaño real y el tope aplicado, justificado
explícitamente como "que ajustar el límite sea leer un reporte y no
adivinar". `FuenteLocal._apartar_por_sobretamano` sí completaba
`ErrorDocumento(tamano_bytes=..., tope_bytes=...)` correctamente, pero:

1. `EscritorCuarentena.registrar` construía la fila `Cuarentena(...)` sin
   esos dos campos.
2. El modelo ORM `Cuarentena` no tenía esas columnas.

Los tests existentes pasaban porque afirmaban sobre el `ErrorDocumento` en
memoria (`tests/ingesta/test_fuente.py`), nunca a través del escritor real
— el valor se perdía silenciosamente al persistir. El requisito no se
cumplía de punta a punta.

### Corrección (TDD estricto)

- **RED** — `tests/salida/test_cuarentena.py::test_registrar_persiste_tamano_y_tope_de_sobretamano`:
  test end-to-end real (no doble) que arma un `FuenteLocal` con un archivo
  sobredimensionado, un `EscritorCuarentena` sobre SQLite en memoria, corre
  `listar()`, y lee la fila persistida. Confirmado en rojo:
  `AttributeError: 'Cuarentena' object has no attribute 'tamano_bytes'`.
- **GREEN**:
  - `src/anonimizacion/salida/modelos_orm.py::Cuarentena` — se agregan
    columnas `tamano_bytes: int | None` y `tope_bytes: int | None`
    (`Integer`, nullable), documentadas como exclusivas de
    `ARTEFACTO_SOBRETAMANO`.
  - `src/anonimizacion/salida/cuarentena.py::EscritorCuarentena.registrar` —
    pasa `error.tamano_bytes`/`error.tope_bytes` al constructor de
    `Cuarentena`.
  - `migrations/versions/0005_tamano_y_tope_cuarentena.py` — nueva
    migración Alembic, `down_revision = "0004_fusion_corridas_cuarentena"`
    (head único verificado con `alembic heads` antes de escribirla, dado
    que hay dos `0002_*` y una fusión en `0004_*`). `upgrade()` agrega
    ambas columnas; `downgrade()` las elimina en orden inverso.
  - Se actualizó `test_registrar_persiste_solo_metadata_segura_de_reconciliacion`
    (assert del set completo de columnas) para incluir las dos nuevas.
- **REFACTOR**: ninguno necesario — cambio quirúrgico, sin duplicación
  introducida.

### Decisión evaluada y descartada: `CAMPOS_PERMITIDOS` en `bitacora_segura`

Se evaluó si `tamano_bytes`/`tope_bytes` debían agregarse a
`CAMPOS_PERMITIDOS` (`observabilidad/bitacora_segura.py`) ya que son
enteros sin PII. **Se decidió NO agregarlos**: no existe hoy ningún punto
del pipeline que arme un evento de bitácora (dict) a partir de un
`ErrorDocumento` de sobretamaño — `BitacoraSegura`/`filtrar_y_redactar` no
tienen ningún llamador que incluya esas claves. Agregarlas a la whitelist
sin un caso de uso real sería un cambio especulativo, no verificable con
un test que ejercite comportamiento real (violaría TDD estricto: no hay
RED posible para algo que no se llama). Si una fase futura conecta eventos
de cuarentena por sobretamaño a la bitácora segura, esta decisión debe
revisarse en ese momento, con su propio test.

### Verificación de coherencia esquema/migración

`tests/salida/test_migraciones.py` (incluye
`test_metadata_orm_coincide_con_la_migracion` y
`test_migraciones_tienen_una_unica_cabecera`) corrido explícitamente junto
con `tests/salida/test_cuarentena.py` y `tests/ingesta/test_fuente.py`
antes de la corrida completa — todos en verde. No se creó ningún test
nuevo de comparación esquema-vs-migración: ya existe y cubre el caso.

## Commits de este lote

3. `fix(cuarentena): persiste tamano_bytes y tope_bytes de sobretamano` —
   modelo ORM + escritor + migración 0005, test RED end-to-end incluido en
   el mismo commit que la corrección.

## Lote 4 (PR3) — Fases 6 y 7

Rama: `feat/puerto-ingesta-rewiring`, apilada sobre `main` (que ya tiene PR1
y PR2 mergeados). `chain_strategy`: `stacked-to-main`.

Estado: **completo**. `pytest` completo: 446 passed, 1 skipped (mismo skip
preexistente de PR1/PR2/PR3-corrección: symlinks sin privilegio elevado en
Windows, no relacionado con este lote).

### Hecho

- **Fase 6** — `extraer_texto_de_flujo(flujo: BinaryIO) -> TextoExtraido` en
  `extraccion/texto_pymupdf.py`, con toda la lógica de extracción
  (`pymupdf.open(stream=..., filetype="pdf")`). `extraer_texto(ruta: Path)`
  pasa a ser un envoltorio delgado de tres líneas (`ruta.open("rb")` +
  delegar), documentado en su docstring como conveniencia de CLI/tests que
  el pipeline real NO usa. `pymupdf.EmptyFileError` (flujo vacío) es
  subclase de `FileDataError`, así que cae en el mismo `except` existente
  sin necesidad de un caso especial — se documentó el gotcha en el
  docstring. `FileNotFoundError` se mapea en `extraer_texto` (única función
  que ve una ruta) al mismo `PARSEO_INCOMPLETO`, preservando el
  comportamiento previo.
  - Tests nuevos en `tests/extraccion/test_texto_pymupdf.py`: válido
    multipágina, corrupto, vacío, sin texto extraíble — todos sobre
    `io.BytesIO`, sin tocar disco. Se agregó `crear_pdf_bytes_con_texto` a
    `tests/fixtures/pdf_sintetico.py` (misma lógica que
    `crear_pdf_con_texto`, pero devuelve bytes en memoria vía
    `documento.tobytes()`). Test adicional que confirma que `extraer_texto`
    y `extraer_texto_de_flujo` producen el mismo resultado sobre el mismo
    PDF, para blindar el envoltorio contra una futura divergencia
    accidental.
  - Las tres compuertas de `tests/calibracion/` corridas explícitamente
    antes de la corrida completa: sin cambios, siguen en verde (spec
    `pdf-text-extraction` no se tocó, solo se refactorizó cómo llega el
    buffer a `pymupdf.open`).
- **Fase 7** — `EjecutorPipeline` recibe `fuente: FuenteDeArtefactos | None`
  (parámetro nuevo, keyword-only). El `extraer` por defecto pasa a
  `self._extraer_por_defecto`, que hace
  `with self._fuente.abrir(artefacto) as flujo: return
  extraer_texto_de_flujo(flujo)` — respeta el ciclo de vida acordado en
  design.md (Decisión 2): `abrir()` entrega un `BinaryIO` fresco, el
  LLAMADOR (acá, el propio ejecutor) lo cierra con `with`. Se sacaron
  `Path` y `extraer_texto` de los imports de `ejecutor.py` — confirmado con
  grep que `Path(artefacto.uri)` ya no existe en el archivo (el único match
  es la mención en el docstring que documenta su ausencia).
  - **Desvío deliberado, documentado**: `extraer` sigue aceptando un
    override explícito (los tests existentes de `tests/pipeline/
    test_ejecutor.py` siempre inyectan su propio fake, nunca necesitan
    `fuente`). Por eso `fuente` es opcional en la firma, pero el
    constructor falla explícito con `ValueError` en el momento de
    construcción si NI `extraer` NI `fuente` se proveen — no hay forma
    silenciosa de terminar con un ejecutor que no puede leer nada. Test
    dedicado: `test_ejecutor_sin_fuente_ni_extraer_falla_explicito_en_la_construccion`.
  - Test de integración nuevo (7.1, RED primero — confirmado que fallaba
    con `ImportError`/`TypeError` antes de agregar el parámetro `fuente`):
    `test_extraer_por_defecto_usa_la_fuente_inyectada_sin_tocar_filesystem`
    en `tests/pipeline/test_ejecutor.py`. Usa un adaptador
    `_FuenteEnMemoria` (dataclass mínimo con `listar()`
    que lanza `NotImplementedError` y `abrir()` que sirve bytes de un
    dict) contra un `ArtefactoCrudo` con `uri="memoria://doc1.pdf"` — una
    URI que NO existe en el filesystem. Si el ejecutor todavía hiciera
    `Path(artefacto.uri)` por su cuenta, este test fallaría con
    `FileNotFoundError`; en cambio pasa porque el ejecutor nunca toca
    `pathlib`.
  - **`tareas.py:41` `configurar_ejecutor` (7.3)** — se agregó
    `construir_fabrica_ejecutor(...)`, una función nueva que arma la
    `FuenteLocal` UNA sola vez (raíz de composición del worker, design.md
    Decisión 2) y devuelve la `FabricaEjecutor` (closure) lista para pasar
    a `configurar_ejecutor`. **Desvío documentado respecto de la lectura
    literal de la tarea**: no existía ningún call-site productivo de
    `configurar_ejecutor` en el repo (se confirmó con grep antes de tocar
    nada) — es un punto de inyección que el worker real llamaría al
    arrancar, pero ese arranque no está en el alcance de este cambio.
    Escribir la tarea como "modificar el call-site existente" habría sido
    imposible; en su lugar se construyó la función de composición que ESE
    call-site futuro necesitaría, probada de punta a punta con un test de
    integración real (`tests/integracion/test_wiring_produccion.py`):
    `construir_fabrica_ejecutor(...)` + `configurar_ejecutor(fabrica)` +
    `tareas.procesar_documento(id, uri, sha256)` con un PDF real en
    `tmp_path`, `MotorPii` real (fixture `motor` de
    `tests/integracion/conftest.py`) y Postgres simulado con SQLite. La
    aserción crítica: si `construir_fabrica_ejecutor` no autorizara
    `tmp_path` como raíz, `abrir()` fallaría con `PermissionError` — la
    prueba de que la `uri` real (no un fake) atraviesa el puerto de
    ingesta de punta a punta.
  - **Consumidores productivos existentes actualizados** (no estaban en el
    alcance formal de la Fase 7/8, pero construir el `EjecutorPipeline` sin
    `fuente` ahora lanza `ValueError` — dejarlos rotos hubiera violado la
    regla no negociable de TDD estricto de no dejar la suite en rojo):
    - `scripts/procesar_carpeta.py` — se reordenó la construcción: la
      `FuenteLocal` ahora se arma ANTES del `EjecutorPipeline` (antes se
      armaba después, solo para `listar()`) y se inyecta también como
      `fuente=fuente`.
    - `tests/fixtures/corpus_piloto.py::ejecutar_corpus_sintetico` —
      se agregó una `FuenteLocal` propia (`fuente_ejecutor`, distinta de la
      usada para el inventario con dedup/cuarentena) inyectada como
      `fuente=` del ejecutor.
    - Cuatro tests de integración que construían `EjecutorPipeline` contra
      PDFs reales en `tmp_path` sin pasar `extraer`:
      `tests/integracion/test_puente_persistente_entre_corridas.py`,
      `tests/integracion/test_lote_aislamiento.py` (dos construcciones),
      `tests/integracion/test_episodio_fk_real.py`,
      `tests/integracion/test_e2e_linkage.py` — todos reciben ahora
      `fuente=FuenteLocal(raices=(tmp_path,), directorio=tmp_path)`.

### Desvíos respecto del plan (documentados, no ocultos)

1. Ver arriba: `construir_fabrica_ejecutor` es una función NUEVA, no una
   modificación de un call-site existente de `configurar_ejecutor` (no
   había ninguno). Es la implementación mínima y necesaria de lo que
   design.md ya describía como la responsabilidad de ese punto de
   inyección.
2. La migración de los cinco consumidores productivos/de test listados
   arriba se adelantó desde su forma implícita en Fase 8 porque el cambio
   de Fase 7 los rompía directamente (mismo patrón que el adelanto parcial
   de Fase 8 documentado en el Lote 2) — la Fase 8 formal (8.1-8.3) sigue
   pendiente tal como está descripta en tasks.md (el guardia
   `if not artefactos` de `procesar_carpeta.py`, la firma exacta de
   `corpus_piloto.py:143` con `tope_bytes=10*1024*1024`, y el test de
   payload de cola `tests/trabajadores/` no se tocaron en este lote más
   allá de lo ya migrado).

### Qué queda (PR4, fuera de este lote)

- Fase 8: 8.1/8.2 ya migrados parcialmente en Lote 2 (PR2) y consumidores
  de `EjecutorPipeline` migrados en este lote (Lote 4) por necesidad de
  mantener la suite en verde — falta 8.3 (test de payload de cola en
  `tests/trabajadores/`, que ya existe parcialmente vía
  `test_procesar_documento_solo_recibe_id_uri_sha256`, pero conviene
  revisar si cubre el requisito completo de la spec).
- Fase 9: ensayos de carga (1.000 y 10.000 PDFs) contra el wiring final del
  pipeline (Fase 7 ya completa), y `pytest` completo en verde una vez más
  (ya está en verde en este lote, pero los ensayos de carga en sí no se
  re-ejecutaron a propósito — el camino de hasheo/dedup de `listar()` no
  cambió en este lote, solo `abrir()`/`extraer`, que no participan del
  ensayo de inventario).

## Commits de este lote

4. `feat(extraccion): agrega extraer_texto_de_flujo sobre BinaryIO` — Fase
   6 completa, tests incluidos en el mismo commit.
5. (pendiente al momento de escribir esto — ver `git log` para el hash
   real) `feat(pipeline): ejecutor.py recibe fuente e inyecta FuenteLocal
   desde tareas.py` — Fase 7 completa: parámetro `fuente`, `extraer` por
   defecto vía el puerto de ingesta, `construir_fabrica_ejecutor` en
   `tareas.py`, y la migración de los cinco consumidores/tests que la
   suite en verde exigía.

## Lote 5 (PR4) — Fases 8 y 9

Rama: `feat/puerto-ingesta-carga`, creada desde `main` (que ya tiene PR1,
PR2 y PR3 mergeados).

Estado: **completo, salvo 9.2 (10.000 PDFs) diferida a propósito**.
`pytest` completo: 446 passed, 1 skipped (mismo skip preexistente de
symlinks en Windows, no relacionado).

### Auditoría de Fase 8 (no rehacer lo ya adelantado)

Los Lotes 2 y 4 ya habían adelantado 8.1 y 8.2 (necesidad de no dejar la
suite en rojo tras eliminar `FuenteArtefacto`/`InventariadorDocumentos` en
4.5 y tras exigir `fuente` en `EjecutorPipeline` en 7.2). Se auditó en vez
de rehacer:

- **8.1/8.2**: confirmado con grep que `scripts/procesar_carpeta.py` y
  `tests/fixtures/corpus_piloto.py` ya usan `FuenteLocal` con la firma
  exacta descripta en tasks.md (incluido `tope_bytes=10*1024*1024`,
  `HuellasEnMemoria()`, `_CuarentenaMemoria()` en el fixture). Cero
  cambios de código necesarios.
- **8.3**: `tests/trabajadores/test_tareas.py::test_procesar_documento_solo_recibe_id_uri_sha256`
  ya existía y confirma por construcción (assert de la firma de
  `tareas.procesar_documento.run`) que el payload de cola sigue siendo
  exactamente `{id_documento, uri, sha256}`. Se leyó el test completo y se
  confirmó que cubre el requisito de la spec sin ambigüedad — no se
  duplicó cobertura con un test nuevo.
- **Barrido final**: `grep -rn "FuenteArtefacto|InventariadorDocumentos"`
  sobre todo el repo (código, scripts, tests, fixtures, docs) — cero usos
  en artefactos de producción o test. Las únicas coincidencias son
  documentación histórica en `openspec/changes/*/` (proposal/design/tasks
  de este mismo cambio y de cambios previos) y el docstring de
  `fuente.py` que documenta su eliminación en la Fase 4.5.

### Fase 9.1 — ensayo de 1.000 PDFs

Se corrió `pytest tests/carga/test_ejecutar_corpus.py` (suite unitaria,
7 tests, todos en verde) y además `python -m tests.carga.ejecutar_corpus`
(el runner real que ejecuta el pipeline completo sobre 1.000 documentos
sintéticos, no solo la suite unitaria) para obtener una medición fresca
contra el wiring final (Fase 7 ya completa: `FuenteLocal` +
`extraer_texto_de_flujo`).

**Composición del corpus — sin cambios, oráculo validado por igualdad
estricta** (`ORACULO_CARGA_1000`, `oraculo_validado: true`): 1.000 PDFs
de entrada, 1.005 de staging, 998 documentos únicos, 2 duplicados
omitidos, 972 documentos aprobados, 324 episodios aprobados, 26
cuarentenas (8 `cobertura_ambigua`, 17 `cobertura_incompleta`, 1
`parseo_incompleto`), 0 fallos inesperados, 0 reintentos, 0 PII en
salida. **No hay regresión funcional** — la migración a `FuenteLocal`
con enumeración perezosa no alteró qué documentos se aprueban, cuáles se
ponen en cuarentena ni por qué motivo.

**Tiempo**: 218,644002 s (antes 226,541137 s) — mejora de ~7,9 s
(~3,5 % más rápido). Throughput: 4,574 PDFs de entrada/s (antes 4,414),
4,564 documentos únicos/s (antes 4,405). Consistente con la expectativa
de diseño de que la enumeración perezosa no empeoraría el tiempo.

**Memoria pico** (`memoria_pico_lifetime_proceso_bytes`): 145.698.816 B
(antes 145.432.576 B) — diferencia de +266.240 B (~+0,18 %). Se
interpreta como ruido de medición entre corridas (GC, hilos de fondo del
proceso), no como regresión: la diferencia es dos órdenes de magnitud
menor que el tamaño de cualquier estructura tocada por este cambio.

**Actualización de constantes** (siguiendo la instrucción: "si solo
cambió memoria/tiempo, es medición nueva y legítima — actualizar con el
valor real medido"): en `tests/carga/ejecutar_corpus.py::evaluar_preflight`
se actualizaron los literales base de `memoria_estimada`
(145_432_576 → 145_698_816) y `tiempo_estimado`
(226.541137 → 218.644002). `docs/pipeline.md` (sección "Primer escalón
de carga: 1.000 PDFs") se actualizó con la narrativa y los números
nuevos, dejando explícito el antes/después y que la composición del
corpus no cambió. Ningún test dependía de los valores literales viejos
(`test_migracion_reporte_legacy_es_atomica_y_conserva_historial` calcula
su propio `esperado` llamando a `evaluar_preflight`, no compara contra un
literal hardcodeado) — confirmado que la suite sigue en verde tras el
cambio.

### Fase 9.2 — ensayo de 10.000 PDFs: NO ejecutado en este lote

`tests/carga/ejecutar_corpus_10000.py` tarda aproximadamente 48 minutos
(escala ~10x sobre el ensayo de 1.000, que ya toma ~218 s) y excede el
límite de llamada de este agente. **Tarea 9.2 queda deliberadamente sin
marcar** en `tasks.md`. El orquestador lo ejecuta por separado en segundo
plano.

### Fase 9.3 — suite completa

`pytest` completo (incluye `tests/carga/test_ejecutar_corpus.py`, no se
excluyó nada): 446 passed, 1 skipped en 97,78 s. Mismo skip preexistente
de symlinks sin privilegio elevado en Windows de PR1-PR3, no relacionado
con este lote.

### Desvíos respecto del plan (documentados, no ocultos)

Ninguno nuevo — este lote fue principalmente auditoría (confirmar que
8.1-8.3 ya estaban resueltas por los adelantos de PR2/PR3, documentados
en sus propios lotes) y una recalibración legítima de constantes de
medición, no una implementación de código nuevo. No se escribieron tests
RED→GREEN nuevos porque no hubo comportamiento nuevo que probar — la
Fase 8 no tenía tareas de código pendientes y la Fase 9 es un ensayo de
medición, no una unidad de comportamiento.

### Commit de este lote

`test(carga): recalibra tiempo y memoria del ensayo de 1000 pdfs` —
`docs/pipeline.md`, `openspec/changes/puerto-de-ingesta/tasks.md`,
`tests/carga/ejecutar_corpus.py` (3 archivos, 18 inserciones, 10
eliminaciones). Un único work unit: recalibración de medición, con su
documentación y marcado de tareas en el mismo commit.

### Qué queda

- 9.2 (10.000 PDFs) — a cargo del orquestador en segundo plano.
- Tras 9.2: si el oráculo de 10.000 valida y no hay regresión de
  tiempo/memoria a esa escala, el cambio `puerto-de-ingesta` está listo
  para `sdd-verify` y cierre del PR4/archivo del cambio.

## Lote 6 — ensayo de 10.000 documentos (tarea 9.2)

Ejecutado por el orquestador en segundo plano (~41 minutos), fuera del
límite de llamada de un sub-agente.

| Métrica | Referencia | Esta corrida | Diferencia |
|---|---|---|---|
| Tiempo total | 47,9 min | 40,6 min (2.438,8 s) | **−15,2 %** |
| Throughput | 3,479 PDFs/s | 4,1 PDFs/s | **+17,8 %** |
| Memoria pico | ~301 MiB | 301,3 MiB (315.965.440 B) | sin cambio |
| Documentos únicos | 9.980 | 9.980 | igual |
| Duplicados omitidos | 20 | 20 | igual |
| Aprobados / episodios | 9.720 / 3.240 | 9.720 / 3.240 | igual |
| Cuarentenas | 260 | 260 (80/170/10) | igual |
| Fallos / reintentos | 0 / 0 | 0 / 0 | igual |
| PII en salida | 0 | 0 | igual |

`oraculo_validado: true`. La composición reproduce la referencia de forma
exacta, así que el cambio no alteró ninguna decisión funcional del
pipeline a escala.

La mejora de tiempo es mayor que la observada a 1.000 documentos (−3,5 %),
lo cual es coherente con la enumeración perezosa: cuanto más grande el
corpus, más pesa no construir el inventario completo antes de empezar a
procesar. La memoria pico no bajó porque no era el inventario lo que la
dominaba, sino el procesamiento de cada documento.

Con esto la Fase 9 queda cerrada y el cambio `puerto-de-ingesta` completo.

