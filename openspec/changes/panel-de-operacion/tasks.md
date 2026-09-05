# Tareas: panel de operación

Comando de test del proyecto: `pytest` (`pyproject.toml`, `testpaths = ["tests"]`). Carga: `pytest tests/carga/`.

**STRICT TDD MODE ACTIVO.** Cada comportamiento se ejecuta en su propio ciclo RED (test que falla
por la razón correcta, nombrado antes que la implementación) → GREEN (mínimo código para pasar) →
REFACTOR (limpieza sin cambiar comportamiento). No se agrupan varios comportamientos en un solo
ciclo. Ningún ítem GREEN se marca sin su RED previo en rojo primero.

## ADVERTENCIA para quien revise el PR del Tramo 1

**El Tramo 1 mergea algo que todavía no se observa desde ninguna pantalla.** No agrega ni cambia
ninguna ruta web, ninguna plantilla HTML. Su criterio de verificación son la migración `0008`, la
presencia de `corrida_id` en `RegistroAnonimizado`/`ErrorDocumento`, y la idempotencia de
cuarentena — **NO el panel**. Si al revisar este PR no aparece ninguna pantalla nueva, es lo
esperado: el panel llega en los Tramos 4 y 5. Rechazarlo por "no se ve nada" sería el criterio
equivocado; aprobarlo sin correr `pytest tests/salida/test_migraciones.py tests/web/test_reporte_cuarentena.py`
también lo sería.

## Conflicto de especificación — verificado como resuelto, no bloquea

`design.md` dejó abierta una pregunta bloqueante: la Decisión 3 (rechaza `corrida_id` en `episodio`
y en las tablas de medición) contradecía, según el propio diseño, el Requisito 1 de
`trazabilidad-por-corrida`. Se releyó `specs/trazabilidad-por-corrida/spec.md` para esta fase de
tareas: el Requisito 1 **ya establece** "`episodio` **MUST NOT** llevar identificador de corrida" y
"Las tablas de medición **MUST NOT** llevar identificador de corrida tampoco" — coincide con la
Decisión 3, no la contradice. La especificación fue reconciliada antes de llegar a esta fase. No
queda ninguna pregunta bloqueante.

Limitación conocida y fuera de alcance (documentada en `design.md`, no bloquea): reprocesar el
mismo corpus bajo una corrida **nueva** (no la misma) muestra todo como residuo, porque
`escribir_registro` no reescribe la fila de `estudio` ya existente con el nuevo `corrida_id`. El
criterio "reprocesar no cambia ningún conteo" se verifica para reanudar la **misma** corrida, que
es el caso operativo real.

## Decisiones de diseño ya cerradas (no se replantean en esta fase)

- `corrida_id` es un parámetro hermano del lote (`procesar_lote(..., corrida_id=)`,
  `procesar_grupo(corrida_id, referencias)`), nunca una cuarta clave de la referencia de cola
  (Decisión 1). El centinela de claves exactas de `procesar_grupo` se extiende, no se relaja.
- `corrida_id` viaja en `RegistroAnonimizado` y `ErrorDocumento` (campo opcional al final, mismo
  precedente que `clave_documento`), no en la firma de `DestinoEscritura`/`DestinoCuarentena`
  (Decisión 2).
- `corrida_id` va **sólo** a `estudio` y `cuarentena`. `episodio` y las tablas de medición **no**
  lo llevan (Decisión 3 — ver reconciliación arriba).
- Idempotencia de cuarentena: `UNIQUE(corrida_id, id_documento)`, guarda de dos capas
  (`SELECT` en la misma transacción + `except IntegrityError`), igual patrón que
  `escribir_registro`. `NULL` no colisiona con `NULL`: sin corrida no hay garantía (Decisión 4).
- `documento_corrida` es inventario puro, escrito una vez con `registrar_documentos` por lotes de
  1000; `DocumentoCorrida.avanzar_a`, `_TRANSICIONES_DOCUMENTO`, `actualizar_documento` y el enum
  `EstadoDocumentoCorrida` **no se tocan**. El panel **MUST NOT** leer `documento_corrida.estado`
  (Decisión 5).
- `procesar_lote` debe devolver un resultado por ítem incluso si la coordinación deja pendientes;
  `_GRUPO_ES_UNIDAD_COMPLETA` se nombra explícitamente y `_coordinar_resueltos` falla ruidoso ante
  un pendiente no contabilizado (Decisión 6).
- `construir_fabrica_ejecutor` gana `metricas`/`bitacora` opcionales con semántica
  `None = producción`; tres tests ejercitan la raíz de composición real, no un doble (Decisión 7).
- El embudo se calcula sobre documentos con desenlace (`publicados + apartados`); el residuo
  (`entraron - con_desenlace`) se expone **con signo**, nunca `max(0, …)` (Decisiones 8 y 9). Un
  residuo negativo es la única señal de que un documento quedó contado en ambos destinos.
- Sin framework: WSGI crudo + polling `fetch`/`setInterval` en línea, cero dependencias nuevas
  (Decisión 10).

## Unidades de trabajo (Tramos → PRs encadenados)

Estrategia de entrega: `auto-chain`. Estrategia de cadena: `stacked-to-main` (cada PR mergea a
main en orden). El corte natural de dos tramos (esquema+propagación / web) fue validado y
**no alcanza**: el primer tramo así estimado supera las 700 líneas. Se mantiene el corte en
**cinco** tramos que ya propone `design.md`, validado abajo tramo por tramo.

| # | Tramo | Qué entra | Qué NO entra | Líneas est. | Riesgo 400 líneas |
|---|---|---|---|---|---|
| 1 | Esquema e idempotencia de cuarentena | Migración `0008`; `corrida_id`/`creado_en` en `modelos_orm`; `corrida_id` en `RegistroAnonimizado`/`ErrorDocumento`; guarda de dos capas en `EscritorCuarentena`; RED que reproduce el conteo doble de `GET /cuarentena` | Cualquier ruta o plantilla nueva; propagación de `corrida_id` por el pipeline | ~370 | Medium |
| 2 | Propagación e inventario | `procesar_lote(corrida_id=)`, `procesar_grupo(corrida_id, …)`, partición total del lote, `registrar_documentos`, `LanzadorCorrida`, `CuarentenaDeCorrida`, `scripts/procesar_carpeta.py` | Observabilidad; embudo; rutas web | ~410 | High (excede el presupuesto; ver nota) |
| 3 | Cableado de observabilidad | `metricas`/`bitacora` en `construir_fabrica_ejecutor`; `_observar_sin_romper`; los tres centinelas de la Decisión 7 | Nada del panel ni del embudo — es independiente de 4 y 5 | ~250 | Low |
| 4 | Modelo de lectura y JSON | `embudo_corrida.py`; memoización; los seis bordes; residuo con signo; `servicio_corridas.py`; `GET /corridas/{id}/embudo`; orden de despacho; arranque sin base de lectura | `plantilla_panel.py`; `GET /panel/{id}`; `scripts/servir_panel.py` | ~390 | Medium |
| 5 | Pantalla y punto de entrada | `plantilla_panel.py`; polling en línea; ficha de descuadre; `scripts/servir_panel.py`; `GET /panel/{id}` | Nada del JSON — reutiliza el Tramo 4 | ~320 | Low |

**Frontera de reversión de cada tramo:**

| # | Frontera de reversión |
|---|---|
| 1 | `downgrade` de `0008`. El código nuevo no tiene llamadores con `corrida_id` todavía: revertirlo no toca ningún camino vivo |
| 2 | Revertir el código: `corrida_id` vuelve a `None` en todas partes y las columnas quedan nulas — el estado del Tramo 1 |
| 3 | Revertir el código. No hay esquema ni datos de por medio |
| 4 | Revertir el código; las rutas nuevas desaparecen, las existentes quedan como estaban |
| 5 | Revertir el código. El JSON del Tramo 4 sigue sirviendo sin pantalla |

**Criterio de verificación de cada tramo:**

| # | Comando | Qué debe dar verde |
|---|---|---|
| 1 | `pytest tests/salida/test_migraciones.py tests/salida/test_modelos_orm.py tests/web/test_reporte_cuarentena.py tests/dominio/` | `upgrade`/`downgrade` de `0008` contra SQLite con duplicados previos; registrar dos veces deja una fila; dos corridas dejan dos; el conteo doble de `GET /cuarentena` queda cerrado |
| 2 | `pytest tests/pipeline/ tests/integracion/test_reprocesar_no_duplica.py` | El centinela de partición total pasa de rojo a verde; `corrida_id` llega a `estudio` y a `cuarentena` por el camino de éxito y por el de fallo |
| 2.5 | `pytest tests/ingesta/ tests/scripts/` | El script produce una corrida con inventario; el sobretamaño apartado antes de tener huella queda igualmente atribuido |
| 3 | `pytest tests/pipeline/ tests/carga/` | Los tres centinelas de observabilidad verdes; los ensayos de mil y diez mil sin degradación de tiempo |
| 4 | `pytest tests/web/test_embudo_corrida.py tests/web/test_rutas_corridas.py` | `GET /corridas/{id}/embudo` responde números correctos; los seis bordes cubiertos; **el test de solapamiento reporta `residuo < 0` y `cierra: false`**; el arranque sin motor responde 503, no falla |
| 5 | `pytest tests/web/` | La página se sirve desde un proceso real; no referencia la red; lleva script en línea; dibuja el descuadre; `tests/web/test_plantilla_reporte.py:59-71` sigue en verde |

**Dependencias**: 1 → 2 es dura (no hay dónde escribir `corrida_id` antes del esquema). 3 es
independiente de 4 y 5 — puede adelantarse o atrasarse en la cadena sin romper nada. 4 depende de 2
(sin atribución no hay qué contar). 5 depende de 4.

**Nota sobre el Tramo 2 (High risk)**: es el más grande y el más difícil de partir más: la firma de
`procesar_lote`, `procesar_grupo`, `registrar_documentos` y `LanzadorCorrida` forman una sola
cadena de dependencia — partirlo a la mitad dejaría un PR con una firma nueva sin ningún llamador
real que la ejercite de punta a punta. Se mantiene como una unidad; si al implementar se acerca a
~450 líneas reales, extraer `scripts/procesar_carpeta.py` (Fase 6.8-6.9) a un PR 2.5 antes de
seguir con el Tramo 3.

---

## Fase 1 (Tramo 1): `corrida_id` en los dataclasses de dominio

- [x] 1.1 RED: en `tests/dominio/test_modelos.py`, test que instancia `RegistroAnonimizado` con
      `corrida_id: str | None` y falla porque el campo no existe.
- [x] 1.2 RED: test que confirma que `RegistroAnonimizado()` sin `corrida_id` sigue construyéndose
      (default `None`) — no rompe fixtures de otras fases.
- [x] 1.3 GREEN: agregar `corrida_id: str | None = None` al final de `RegistroAnonimizado`
      (`dominio/modelos.py`).
- [x] 1.4 RED: en `tests/dominio/test_errores.py`, test que instancia `ErrorDocumento` con
      `corrida_id: str | None` y falla porque el campo no existe.
- [x] 1.5 GREEN: agregar `corrida_id: str | None = None` al final de `ErrorDocumento`
      (`dominio/errores.py`).
- [x] 1.6 REFACTOR: `pytest tests/dominio/ tests/salida/ tests/pipeline/` en verde — confirmar que
      ningún llamador existente usa argumentos posicionales que el campo nuevo (al final, con
      default) pudiera romper.

## Fase 2 (Tramo 1): migración `0008_corrida_en_salida`

- [x] 2.1 RED: en `tests/salida/test_migraciones.py`, test que corre `upgrade()` hasta `head` sobre
      SQLite en memoria y falla porque `0008` no existe (o las columnas/índices esperados no
      calzan).
- [x] 2.2 RED: test que prepara `cuarentena` con dos filas duplicadas de `id_documento`
      preexistentes (`corrida_id` ausente) **antes** de `upgrade()` — fija el punto de partida: hay
      duplicados previos sin corrida en el sistema real.
- [x] 2.3 GREEN: crear `migrations/versions/0008_corrida_en_salida.py`,
      `down_revision = "0007_clave_documento"`. `upgrade()`: `op.batch_alter_table("estudio")` →
      `add_column("corrida_id", String(36), nullable=True)` +
      `add_column("creado_en", DateTime(timezone=True), nullable=True)` +
      `create_index("ix_estudio_corrida_creado", ["corrida_id", "creado_en"])`;
      `op.batch_alter_table("cuarentena")` → `add_column("corrida_id", String(36), nullable=True)`
      + `create_unique_constraint("uq_cuarentena_corrida_documento", ["corrida_id", "id_documento"])`
      + `create_index("ix_cuarentena_corrida_creado", ["corrida_id", "creado_en"])`;
      `drop_index("ix_documento_corrida_corrida_id")`. `batch_alter_table` obligatorio: SQLite no
      soporta agregar `UNIQUE` con `ALTER TABLE` directo.
- [x] 2.4 GREEN: confirmar que las dos filas duplicadas de 2.2 **siguen existiendo** tras
      `upgrade()` — la restricción única se crea sobre duplicados preexistentes sin deduplicar ni
      rellenar nada (los `NULL` no colisionan entre sí).
- [x] 2.5 RED: test de `downgrade()` — `upgrade()` seguido de `downgrade()` sobre SQLite en memoria
      confirma que el esquema vuelve al estado de `0007` (columnas e índices nuevos fuera).
- [x] 2.6 GREEN: `downgrade()` — inverso simétrico de 2.3 sobre `cuarentena` y `estudio`.
- [x] 2.7 REFACTOR: correr `upgrade`/`downgrade`/`upgrade` para confirmar idempotencia estructural,
      mismo patrón que `0007`.

## Fase 3 (Tramo 1): `EscritorCuarentena` — idempotencia y el bug de conteo doble YA MERGEADO

- [x] 3.1 RED — reproduce el defecto antes de arreglarlo (código ya mergeado): en
      `tests/web/test_reporte_cuarentena.py`, dos llamadas a `EscritorCuarentena.registrar` con el
      **mismo** `ErrorDocumento(id_documento=...)` contra el esquema y el código **actuales** (sin
      guarda) dejan dos filas en `cuarentena`, y `construir_reporte` las cuenta dos veces. Este
      test debe estar en rojo (es decir, confirmar la duplicación) antes de aplicar 3.5.
- [x] 3.2 GREEN (esquema): en `salida/modelos_orm.py`, agregar `corrida_id: Mapped[str | None]` y
      `creado_en: Mapped[datetime | None]` a `Estudio`; `corrida_id: Mapped[str | None]` a
      `Cuarentena` con `UniqueConstraint("corrida_id", "id_documento", name="uq_cuarentena_corrida_documento")`
      en `__table_args__` — debe coincidir exactamente con la migración de 2.3.
- [x] 3.3 RED: test que inserta dos filas `Cuarentena` con el mismo `(corrida_id, id_documento)`
      directo contra SQLite en memoria y confirma `IntegrityError`.
- [x] 3.4 RED: test que confirma que dos filas `Cuarentena` con `corrida_id=None` **no** colisionan
      entre sí aunque compartan `id_documento` — las filas legadas y los fixtures sin corrida
      siguen sin garantía.
- [x] 3.5 GREEN: en `EscritorCuarentena.registrar` (`salida/cuarentena.py`), guarda de dos capas
      calcada de `escribir_registro`: dentro de `sesion.begin()`, `SELECT` previo por
      `(corrida_id, id_documento)` si `error.corrida_id is not None` — si ya existe, retornar sin
      escribir; envolver el `add`/flush en `try/except IntegrityError: pass`. Propagar
      `corrida_id=error.corrida_id` al construir `Cuarentena(...)`.
- [x] 3.6 GREEN: confirmar que 3.1 pasa a verde — registrar dos veces el mismo error con
      `corrida_id` fija deja una sola fila y `construir_reporte` cuenta una vez.
- [x] 3.7 RED: test que registra el mismo `id_documento` bajo dos `corrida_id` distintas y confirma
      que quedan **dos** filas — historial entre corridas, no duplicado.
- [x] 3.8 RED: test de concurrencia — dos registros del mismo `(corrida_id, id_documento)` sin que
      el primero haya comiteado (dos sesiones contra el mismo engine SQLite, o mock de sesión)
      confirma que la segunda captura `IntegrityError` sin propagar.
- [x] 3.9 REFACTOR: `pytest tests/salida/ tests/web/test_reporte_cuarentena.py` en verde; actualizar
      el docstring de `EscritorCuarentena.registrar` para describir la guarda nueva.

> **El Tramo 2 se partió en dos PRs durante el apply.** La implementación completa de las Fases 4-6
> llegó a 763 líneas, muy por encima del presupuesto, y dejaba `LanzadorCorrida` y
> `CuarentenaDeCorrida` sin llamador de producción hasta que se modificara
> `scripts/procesar_carpeta.py`. El corte evita las dos cosas a la vez:
>
> - **PR2 — propagación (Fases 4, 5, 6.10-6.12), ~420 líneas.** `corrida_id` viaja por
>   `procesar_lote`/`procesar_grupo` y llega a las filas. Tiene llamadores reales desde el primer
>   commit.
> - **PR2.5 — inventario (Fases 6.1-6.9), ~400 líneas.** `registrar_documentos`, `LanzadorCorrida`
>   y `CuarentenaDeCorrida` entran **junto con** el cableado del script que los usa, de modo que
>   ninguna pieza queda huérfana ni siquiera transitoriamente.
>
> El motivo de fondo: este proyecto ya arrastra tres subsistemas construidos, verdes y
> desconectados. Un huérfano "por un PR nomás" es exactamente cómo empezaron los tres.

## Fase 4 (Tramo 2): partición total del lote (Decisión 6)

- [x] 4.1 RED: en `tests/pipeline/test_particion_total_del_lote.py` (nuevo), coordinador de
      episodios falso que devuelve un episodio en `episodios_pendientes` no vacío; correr
      `procesar_lote` y afirmar `len(resultados) == len(items)` — **rojo hoy**: los pendientes se
      pierden en silencio.
- [x] 4.2 RED: segundo test en el mismo archivo — el caso normal (sin pendientes) también cumple
      `len(resultados) == len(items)`.
- [x] 4.3 GREEN: en `pipeline/ejecutor.py`, nombrar `_GRUPO_ES_UNIDAD_COMPLETA = True` (reemplaza el
      `True` anónimo de la línea ~366) con el comentario de la invariante; `_coordinar_resueltos`
      lanza `RuntimeError` si algún resuelto no cae ni en aprobados ni en cuarentena.
- [x] 4.4 REFACTOR: `pytest tests/pipeline/` en verde; confirmar que `_GRUPO_ES_UNIDAD_COMPLETA` NO
      se expone como parámetro público — exponerla sin la contabilidad detrás es ofrecer la trampa
      con una perilla.

> **Resuelto durante el apply (tarea 4.1).** El enunciado pedía literalmente
> `len(resultados) == len(items)`, pero la Decisión 6 del diseño elige **fallar ruidoso** con
> `RuntimeError` ante un pendiente no contabilizado. Las dos cosas son excluyentes: una excepción
> no retorna nada que medir. Se resolvió a favor de la decisión cerrada, y el test quedó como
> `pytest.raises(RuntimeError)`.

## Fase 5 (Tramo 2): `corrida_id` viaja por `procesar_lote`/`procesar_grupo`

- [x] 5.1 RED: extender el centinela de claves exactas de `procesar_grupo` — la referencia por
      documento sigue teniendo **exactamente** `{id_documento, uri, sha256}` aunque
      `procesar_grupo` reciba `corrida_id` como parámetro hermano del lote.
- [x] 5.2 RED: test que llama `EjecutorPipeline.procesar_lote(items, corrida_id="c1")` y confirma
      que el `RegistroAnonimizado` emitido trae `corrida_id == "c1"`.
- [x] 5.3 RED: test equivalente para el camino de fallo — un ítem apartado produce un
      `ErrorDocumento` con `corrida_id == "c1"`.
- [x] 5.4 GREEN: agregar `corrida_id: str | None = None` a `procesar_lote`; copiarlo en `_emitir`
      (a `RegistroAnonimizado`) y en `_a_fallo` (a `ErrorDocumento`); agregar
      `corrida_id: str` a `procesar_grupo(corrida_id, referencias)` y propagarlo a `procesar_lote`
      sin tocar la construcción de `ItemLote`.
- [x] 5.5 REFACTOR: `pytest tests/pipeline/` en verde; confirmar por lectura que ningún módulo del
      núcleo importa `RepositorioCorridas` ni consulta la tabla `corrida`.

## Fase 6 (Tramo 2): inventario — `registrar_documentos`, `LanzadorCorrida`, `CuarentenaDeCorrida`

- [x] 6.1 RED: en `tests/ingesta/test_repositorio_corridas.py`, test que llama
      `RepositorioCorridas.registrar_documentos(documentos, tamano_lote=1000)` y falla porque el
      método no existe.
- [x] 6.2 GREEN: agregar `registrar_documentos(documentos, *, tamano_lote=1000) -> int` a
      `RepositorioCorridas` — una sesión por lote de `tamano_lote`, misma guarda de idempotencia
      por `(corrida_id, huella_contenido)` que `registrar_documento`, que se conserva sin cambios.
- [x] 6.3 RED: test que llama `registrar_documentos` dos veces con el mismo lote (misma corrida) y
      confirma que `uq_documento_corrida_huella` evita duplicar el denominador.
- [x] 6.4 RED: en `tests/ingesta/test_lanzador_corrida.py` (nuevo), test que llama
      `LanzadorCorrida.lanzar(ruta)` y confirma `corrida_id` + referencias devueltos, con la
      corrida avanzada `CREADA → INVENTARIANDO → PROCESANDO` — falla porque `LanzadorCorrida` no
      existe.
- [x] 6.5 GREEN: crear `ingesta/lanzador_corrida.py` con `LanzadorCorrida`: crea la `Corrida`,
      avanza a `INVENTARIANDO`, llama `fuente.listar()` con el sumidero decorado, llama
      `registrar_documentos(...)`, avanza a `PROCESANDO`, devuelve `corrida_id` + referencias.
- [x] 6.6 RED: test que confirma que un artefacto apartado por sobretamaño en `FuenteLocal` (antes
      de calcular su huella) llega a cuarentena con el `corrida_id` correcto — falla porque
      `CuarentenaDeCorrida` no existe.
- [x] 6.7 GREEN: crear `CuarentenaDeCorrida` (dataclass frozen que envuelve un `SumideroCuarentena`
      y estampa `corrida_id` en cada `ErrorDocumento` vía `replace()` antes de delegar) en
      `ingesta/lanzador_corrida.py`; `LanzadorCorrida` arma la fuente de enumeración con este
      sumidero.
- [x] 6.8 RED: en `tests/scripts/test_procesar_carpeta.py`, test que confirma que
      `scripts/procesar_carpeta.py` usa `LanzadorCorrida` y propaga `corrida_id` hasta
      `procesar_grupo` — falla porque el script no lo hace todavía.
- [x] 6.9 GREEN: modificar `scripts/procesar_carpeta.py` para usar `LanzadorCorrida` y pasar
      `corrida_id` a `procesar_grupo`.

> **Bug encontrado y cerrado durante el apply de 6.8/6.9 (PR 2.5), fuera del enunciado literal de
> la tarea pero bloqueante para su propio criterio de aceptación**: `EscritorPostgres._insertar`
> (Fase 3, ya mergeada) nunca copiaba `corrida_id` de `RegistroAnonimizado` a la fila `Estudio`, y
> `modelos_orm.py::Estudio.creado_en` no tenía el `default=_ahora_utc` que `design.md` (tabla de
> columnas) ya pedía para esa columna — quedó declarada `nullable=True` sin default, a diferencia
> de `Cuarentena.creado_en`. Ningún test de Fase 3/5 lo detectó porque todos verifican
> `RegistroAnonimizado.corrida_id`/`ErrorDocumento.corrida_id` contra dobles de prueba, nunca contra
> el `EscritorPostgres` real escribiendo en una base. El primer test end-to-end real desde
> `scripts/procesar_carpeta.py` (6.8) lo hizo visible: sin este fix, `corrida_id` quedaba en
> `None` en TODA fila de `estudio`, sin importar qué tan bien propagara el pipeline el parámetro —
> no era un problema del script, era un problema de la Fase 3. Fix de 2 líneas:
> `Estudio(..., corrida_id=registro.corrida_id)` en `_insertar`, y `default=_ahora_utc` agregado a
> la columna. Ningún test existente de Fase 1-6.7 dependía del comportamiento anterior (nadie
> verificaba `creado_en`/`corrida_id` contra `EscritorPostgres` real).

> **Addendum post-revisión fresca (PR 2.5), tres puntos cerrados antes de aprobar:**
>
> 1. **Test unitario aislado del escritor.** `tests/salida/destinos/test_postgres.py` gana
>    `test_escribir_registro_persiste_corrida_id_y_creado_en` (y su contraparte
>    `test_escribir_registro_sin_corrida_id_deja_corrida_id_en_none`, que fija el caso sin corrida):
>    apuntan directo a `EscritorPostgres.escribir_registro` contra el escritor real, sin bajar por
>    `procesar_grupo` ni por el script. Antes de este addendum, la única protección del fix era el
>    test end-to-end de 6.8 — si el bug reaparece, ahora se detecta acá, en el mismo lugar donde se
>    escondió dos PRs.
>
> 2. **El banco de carga y `_DestinoMemoria` — decisión, no divergencia asumida en silencio.**
>    `tests/fixtures/corpus_piloto.py` no pasa por `LanzadorCorrida` ni por `procesar_grupo` (correcto:
>    eso es orquestación administrativa, no algo que el banco deba medir) **y además** escribe contra
>    `_DestinoMemoria`, un doble, no contra `EscritorPostgres` real. Antes del punto 1, eso era un
>    punto ciego: exactamente el tipo de superficie sin cubrir donde se escondió el bug de
>    `corrida_id`/`creado_en` — un destino en memoria nunca iba a ejercitar `_insertar`. **Con el
>    punto 1 cubierto, deja de serlo**: la corrección del escritor real ya tiene su propio test de
>    integración (`test_postgres.py`, aislado), así que el banco puede seguir midiendo throughput
>    puro contra un destino en memoria sin dejar ningún camino de escritura real sin verificar. La
>    separación de responsabilidades queda: `test_postgres.py` prueba que `EscritorPostgres` escribe
>    bien; `corpus_piloto.py` prueba cuánto tarda el pipeline en llegar a escribir, sin que el costo
>    de una sesión SQL real contamine esa medición. No se modificó `corpus_piloto.py`.
>
> 3. **Cambio de comportamiento observable para el operador — documentado, no descubierto después.**
>    Antes de 6.9, el script imprimía por consola `id_paciente`/`id_episodio` truncados de cada
>    éxito (leídos directo de `ExitoDocumento`). Al pasar a `procesar_grupo`, el reporte pasa a
>    construirse desde `resumen_trazable()` (`pipeline/resultado.py`), cuya whitelist fija **no**
>    incluye esos dos campos — es deliberado en ese módulo, no un descuido de este cambio. Se gana:
>    consistencia con la postura anti-PII del proyecto (el mismo dato que nunca se loguea en la cola
>    ni en la bitácora, tampoco se imprime acá). Se pierde: una ayuda de depuración manual — antes,
>    al correr el script a mano, se podía ver a qué paciente/episodio fue a parar cada documento sin
>    ir a la base; ahora hay que consultar `estudio`/`episodio` directamente por `corrida_id` para
>    esa correlación. Ninguna tarea de 6.8/6.9 mencionaba este cambio de salida; queda asentado acá
>    para que no se descubra el día que alguien la extrañe.

- [x] 6.10 RED: extender `tests/integracion/test_reprocesar_no_duplica.py` a cuarentena — reprocesar
      el mismo grupo no aumenta el conteo de filas en `cuarentena` de esa corrida (spec
      `escritura-idempotente` delta, "reprocesar la misma corrida no duplica el apartado").
- [x] 6.11 GREEN: ajustes de wiring residuales si 6.10 los revela (no debería requerir lógica nueva
      si 3.5 y 5.4 están completas).
- [x] 6.12 REFACTOR: `pytest tests/ingesta/ tests/pipeline/ tests/integracion/test_reprocesar_no_duplica.py`
      en verde.

## Fase 7 (Tramo 3): observabilidad cableada en la raíz de composición (Decisión 7)

- [x] 7.1 RED — `test_la_fabrica_cablea_la_observabilidad`: espía de `ColectorMetricas`/
      `BitacoraSegura` inyectado vía `construir_fabrica_ejecutor(metricas=, bitacora=)`, procesar
      un grupo real de tres PDFs por `tareas.procesar_grupo` (mismo molde que
      `tests/integracion/test_wiring_produccion.py`) y confirmar que el espía recibió
      observaciones — falla porque los parámetros no existen todavía.
- [x] 7.2 GREEN: agregar `metricas: ColectorMetricas | None = None` y
      `bitacora: BitacoraSegura | None = None` a `construir_fabrica_ejecutor`, con la semántica de
      `dormir`/`resolver_claves` (`None` = producción); cablear dentro de `_fabrica()`.
- [x] 7.3 RED — `test_sin_inyeccion_explicita_igual_hay_colector`: construir el ejecutor SIN pasar
      nada e introspeccionar que trae un colector/bitácora reales, no `None`.
- [x] 7.4 GREEN: confirmar/ajustar el default de producción dentro de `_fabrica()` si 7.3 lo exige.
- [x] 7.5 RED — `test_un_colector_que_explota_no_tumba_el_grupo`: colector que lanza excepción en
      todos sus métodos, procesar un grupo real de tres PDFs y confirmar que los tres se publican
      igual (invariante 3 de la propuesta).
- [x] 7.6 GREEN: crear `_observar_sin_romper` en `pipeline/ejecutor.py`; envolver con él
      `incrementar_documento_procesado` (`_emitir`), `incrementar_fallo` (`_a_fallo`), y
      `observar_duracion_ms` (parámetro nuevo `observar: Callable[[str, float], None] | None = None`
      en `_ejecutar_con_reintentos`).
- [x] 7.7 RED: test que confirma que `bitacora.registrar(resultado.resumen_trazable())` se llama
      exactamente una vez por resultado al cerrar `procesar_lote`.
- [x] 7.8 GREEN: agregar esa llamada al cierre de `procesar_lote`, envuelta también en
      `_observar_sin_romper`.
- [x] 7.9 REFACTOR: `pytest tests/pipeline/` en verde; correr los ensayos de carga de mil y diez mil
      y confirmar que el tiempo por documento no se degrada frente a la última corrida validada
      (referencia: `openspec/changes/escritura-idempotente/tasks.md`, Fase 12).

> **Nota de alcance (apply, 7.9)**: por instrucción explícita del maintainer para esta ronda, se
> corrió SOLO el ensayo de mil documentos (dos veces), NO el de diez mil — se evalúa aparte. Ver
> `apply-progress` para los cuatro números crudos y la decisión de no interpretarlos acá.

> **Addendum post-revisión fresca (Tramo 3), dos puntos: uno arreglado, uno documentado sin
> arreglar.**
>
> 1. **Arreglado: `BitacoraSegura` se construía sin `motor_pii` en la fábrica de producción.**
>    `construir_fabrica_ejecutor` ya recibe `motor: MotorPii` como parámetro, pero el default de
>    `bitacora` (cuando no se inyecta explícitamente) era `BitacoraSegura()` a secas — sin pasarle
>    ese motor. El propio docstring de `bitacora_segura.py` dice que sin `motor_pii` la capa 2 de
>    redacción queda en **modo degradado** (solo regex de DNI), y que el composition-root de
>    producción debería compartir una única instancia. Se verificó antes de tocar nada que
>    compartir el motor entre el ejecutor y la bitácora es seguro: `MotorPii.detectar` no acumula
>    estado entre llamadas (es una función pura sobre el texto de entrada contra un
>    `AnalyzerEngine` ya cargado), y el mismo `motor` ya se comparte hoy entre todos los documentos
>    de todos los grupos que procesa un worker (`EjecutorPipeline._emitir` lo inyecta en
>    `construir_registro`/`redactar_texto`, ver `pii/redaccion.py`) — agregar la bitácora como un
>    lector más no introduce ningún estado ni condición de carrera nueva. Se cableó
>    `BitacoraSegura(motor_pii=motor)` como default de producción, y se agregó
>    `test_la_fabrica_comparte_el_motor_pii_con_la_bitacora_de_produccion` en
>    `tests/pipeline/test_observabilidad_cableada.py`, que falla si alguien vuelve a construir la
>    bitácora sin motor en la fábrica.
>
>    **Costo medido, no ignorado**: `MotorPii.detectar()` sobre una cadena corta (un `id_documento`
>    opaco, un valor de enum) tarda ~4,2 ms por llamada medido en esta máquina. La whitelist de
>    `BitacoraSegura` (`CAMPOS_PERMITIDOS`) sólo deja pasar campos estructurados —
>    `id_documento`/`tipo_documento` en un éxito, `id_documento`/`etapa`/`codigo` en un fallo —,
>    ninguno de los cuales es texto libre con PII real; correrles NER es, en la práctica, trabajo
>    sin beneficio de protección adicional sobre esos campos puntuales, pero es exactamente lo que
>    la capa 2 hace por diseño ("por si terminara conteniendo texto libre con PII incrustada por
>    error"). A partir del microbenchmark se estimó un overhead de ~8-13 ms por documento, es decir
>    un **~4-6 %**.
>
>    **Esa estimación resultó equivocada por un factor de cinco, y se midió.** Se corrió el ensayo
>    de mil dos veces con el motor cableado, en la misma máquina y el mismo día que las dos corridas
>    sin cablear, con el corpus y el código idénticos salvo esta línea:
>
>    | Motor en la bitácora | Corrida 1 | Corrida 2 | Promedio |
>    |---|---|---|---|
>    | No | 218,5 s | 216,8 s | 217,7 s |
>    | Sí | 219,9 s | 219,2 s | 219,6 s |
>
>    Diferencia real: **~1,9 s sobre ~218 s, es decir 0,87 %** — no 4-6 %. Sobre una corrida de
>    100.000 documentos estimada en ocho horas, son unos cuatro minutos, no media hora.
>
>    Con ese dato la decisión es clara y se mantiene el cableado: menos del 1 % de rendimiento a
>    cambio de que la segunda capa de redacción opere completa y no en modo degradado. La lección
>    metodológica queda asentada aparte: **un microbenchmark multiplicado por una cantidad supuesta
>    de llamadas no es una medición**, y en este caso erró cinco veces. La decisión correcta se
>    tomó recién con el experimento controlado.
>
> 2. **Documentado, NO arreglado: `ColectorMetricas` no tiene consumidor en producción.**
>    Verificado por lectura: `MetricasEnMemoria` se construye de nuevo dentro de cada llamada a
>    `_fabrica()` (una por grupo/tarea Celery) y se descarta con el `EjecutorPipeline` al terminar
>    esa tarea — no persiste entre grupos, no persiste entre documentos de grupos distintos.
>    Ningún punto de producción llama a `snapshot()` ni a `resumen_operacional()`: el colector
>    **registra y tira**. Esto es asimétrico respecto de `BitacoraSegura`, que sí produce una
>    salida consumible (el logger de Python, que un operador puede leer). A diferencia del punto 1,
>    esto **no se arregla en este cambio**: el embudo del panel (Fases 8-9, Tramo 4) se deriva de
>    la base de datos (`estudio`/`cuarentena`/`documento_corrida`), no del colector de métricas en
>    memoria de un worker — agregar un acumulador por proceso ahora sería construir para un
>    consumidor que todavía no existe, exactamente el patrón de "subsistema huérfano" que este
>    tramo vino a corregir para `observabilidad/`, no a repetir dentro de ella.
>
>    **Pregunta abierta, explícita, no un hallazgo para dentro de seis meses**: ¿`ColectorMetricas`
>    necesita un patrón de agregación por proceso worker (ej. exponerlo vía un endpoint de
>    métricas del propio worker, o volcar `resumen_operacional()` a la bitácora al cerrar la
>    tarea), o directamente no hace falta porque todo lo que el panel necesita ya sale de la base
>    de datos? No se resuelve acá. Si nadie lo consume nunca, la pregunta correcta en algún punto
>    futuro es si `ColectorMetricas`/`MetricasEnMemoria` deberían eliminarse en vez de mantenerse
>    cableados sin lector.

## Fase 8 (Tramo 4): `embudo_corrida.py` — modelo de lectura

- [ ] 8.1 RED: en `tests/web/test_embudo_corrida.py` (nuevo), serie de timestamps sintética que
      confirma el orden de las siete etapas (`ingesta, extraccion, parseo, reconciliacion,
      coordinacion, pseudonimizacion, salida`) — el orden de ejecución, no el del enum `Etapa`.
- [ ] 8.2 GREEN: crear `src/anonimizacion/web/embudo_corrida.py` con `Embudo`, `PerdidaEtapa`,
      `Estimacion` (dataclasses frozen) y la lista explícita de las siete etapas.
- [ ] 8.3 RED — **el centinela de solapamiento, parte aritmética (no diluir)**: embudo sintético con
      más apartados que inventariados produce `residuo < 0` y `cierra is False`, sin ningún
      `max(0, …)` en el camino. Un test que sólo verificara que la suma cierra sería vacío:
      `desconocido` está definido como resto y cerraría siempre.
- [ ] 8.4 GREEN: `residuo = entraron - (publicados + apartados)`, expuesto **siempre con signo**;
      `cierra = residuo >= 0`. Sin clamping en ningún punto del cálculo.
- [ ] 8.5 RED: test que confirma que un documento apartado por `artefacto_sobretamano` cuenta en la
      barra de ingesta pero NO en `throughput_por_hora`.
- [ ] 8.6 GREEN: excluir `artefacto_sobretamano` del cálculo de throughput, conservándolo en el
      conteo de apartados por etapa.
- [ ] 8.7 RED: serie sintética que cubre los seis bordes de "Rango de tiempo restante":
      `entraron == 0` → "midiendo"; `terminados < 200` → "midiendo"; ventana reciente vacía → "sin
      avance en los últimos 5 minutos"; `restante == 0` → "todos los documentos tienen desenlace";
      `restante < 0` → "descuadre"; caso disponible → rango con cota optimista y pesimista.
- [ ] 8.8 GREEN: implementar las tres consultas agregadas del diseño, la memoización de un segundo
      por `corrida_id`, y las reglas de borde de 8.7.
- [ ] 8.9 RED: en `tests/integracion/`, inventariar documentos, publicar algunos, apartar otros, y
      afirmar que el embudo da los números correctos **mientras todas las filas de
      `documento_corrida` siguen en `INVENTARIADO`** — el centinela contra la máquina de estados
      (Decisión 5). Si alguien acopla el embudo al estado, este test se pone rojo.
- [ ] 8.10 GREEN: confirmar que `construir_embudo` nunca lee `documento_corrida.estado` (sólo
      `count(*)`); ajustar si 8.9 revela una lectura indebida.
- [ ] 8.11 RED — **el centinela de solapamiento, camino real completo (Punto 1, no diluir)**:
      destino de escritura falso donde `escribir_registro` **commitea** el `estudio`, la conexión
      se cae antes de que el cliente vea el OK, `_ejecutar_con_reintentos` reintenta con `dormir`
      inyectado, los reintentos se **agotan**, y `ERROR_TRANSITORIO_AGOTADO` envía el mismo
      documento a cuarentena **con el estudio ya escrito**. Correrlo vía `procesar_lote` real
      (Fase 5), construir el embudo sobre el resultado (Fase 8), y afirmar `residuo < 0` y
      `cierra is False`. Sin fabricar el estado inconsistente a mano — el camino tiene que ser el
      real y alcanzable descrito en `design.md`, Decisión 9.
- [ ] 8.12 GREEN: ajustes residuales si 8.11 revela algún punto donde el residuo se recortara o el
      solapamiento no se reflejara (no debería requerir lógica nueva si 8.4 está completa).
- [ ] 8.13 RED: test que confirma que el residuo es cero al terminar una corrida sintética completa
      **sin** fallos de infraestructura — cierra la invariante también en el lado positivo.
- [ ] 8.14 REFACTOR: `pytest tests/web/test_embudo_corrida.py` y los de integración de esta fase en
      verde; confirmar por lectura que `embudo_corrida.py` nunca proyecta `ruta_autorizada` ni
      `huella_contenido`.

## Fase 9 (Tramo 4): `servicio_corridas.py`, rutas, orden de despacho (Punto 4, no diluir)

- [ ] 9.1 RED — **el orden de las ramas de despacho**: en `tests/web/test_rutas_corridas.py`, un
      `GET /corridas/{id}/embudo` contra la aplicación WSGI **actual** falla con 404 porque cae en
      la rama genérica `GET /corridas/...` de `rutas_corridas.py:52`, donde `_consultar_corrida`
      rechaza cualquier identificador que contenga `/`. Este test se escribe y se confirma en rojo
      **antes** de tocar `rutas_corridas.py`.
- [ ] 9.2 GREEN: insertar la comprobación de `GET /corridas/{id}/embudo` **antes** de la rama
      genérica de la línea 52. **No tocar** la rama de `/reintentar` (línea 54): sigue guardada por
      `metodo == "POST"` y funciona correctamente hoy — reordenarla es riesgo sin beneficio y queda
      fuera de este cambio.
- [ ] 9.3 RED: test de no regresión explícito — un `POST /corridas/{id}/reintentar` sigue llegando
      a su rama sin cambio de comportamiento tras 9.2.
- [ ] 9.4 RED: test que confirma que `ServicioCorridas.crear_corrida(ruta)` delega en
      `LanzadorCorrida` y devuelve un estado real — falla porque hoy es un doble.
- [ ] 9.5 GREEN: crear `src/anonimizacion/web/servicio_corridas.py`: `crear_corrida` delega en
      `LanzadorCorrida`; `consultar_corrida` lee el embudo real vía `embudo_corrida.construir_embudo`
      y mapea `documentos_pendientes = sin_desenlace`, `cuarentenas = apartados`;
      `reintentar_corrida` lanza `NotImplementedError`.
- [ ] 9.6 RED: test que confirma que `GET /corridas/{id}/embudo` responde el contrato JSON completo
      (`corrida_id, estado, generado_en, entraron, publicados, apartados, residuo, cierra, marcha,
      etapas, throughput_por_hora, estimacion`) contra un motor real con datos sintéticos.
- [ ] 9.7 GREEN: implementar la ruta, serializando `Embudo` al contrato exacto del diseño.
- [ ] 9.8 RED: test que confirma que `POST /corridas/{id}/reintentar` responde 501 con
      `{"codigo": "reintento_no_implementado"}` — no un 202 falso.
- [ ] 9.9 GREEN: capturar `NotImplementedError` en la ruta y responder 501 con ese cuerpo.
- [ ] 9.10 RED — arranque sin base de lectura (spec `portal-de-corridas` delta): la aplicación WSGI
      se construye con el motor de lectura en `None` y `GET /corridas/{id}/embudo` responde con no
      disponibilidad (503), sin que la construcción de la app falle.
- [ ] 9.11 GREEN: aceptar `motor: Engine | None` en la raíz de composición web; las rutas que
      dependen de él devuelven 503 con cuerpo explícito cuando es `None`.
- [ ] 9.12 REFACTOR: `pytest tests/web/` en verde; confirmar que no se tocó ninguna línea de la rama
      `/reintentar` salvo el manejo del 501.

## Fase 10 (Tramo 5): pantalla y punto de entrada

- [ ] 10.1 RED: en `tests/web/test_plantilla_panel.py` (nuevo), `"http://" not in pagina`,
      `"https://" not in pagina`, `"<script src" not in pagina` **y** `"<script>" in pagina` — el
      polling en línea es un requisito, no un accidente.
- [ ] 10.2 GREEN: crear `src/anonimizacion/web/plantilla_panel.py`: HTML por f-strings, CSS en
      línea, misma paleta que `plantilla_reporte.py`, con el `<script>` de polling
      (`fetch`/`setInterval` 1-2 s) en línea.
- [ ] 10.3 RED: test que confirma que un código de cuarentena con marcado HTML llega escapado, y
      que el script de refresco usa `textContent` — literal ausencia de `innerHTML` en el JS
      embebido.
- [ ] 10.4 GREEN: implementar el escape de contenido dinámico y `textContent` en el refresco.
- [ ] 10.5 RED — **el centinela de solapamiento, parte de pantalla (cierra el Punto 1)**: un embudo
      con residuo negativo se dibuja con su propia ficha ("Descuadre: N documentos con más de un
      desenlace" + explicación) en vez de un cero.
- [ ] 10.6 GREEN: implementar la ficha de descuadre en `plantilla_panel.py`, símbolo y etiqueta
      propios en la paleta de estado.
- [ ] 10.7 VERIFICACIÓN de regresión (Punto 6, no RED/GREEN — es un centinela ya existente): correr
      `tests/web/test_plantilla_reporte.py:59-71` tal cual y confirmar que sigue en verde con el JS
      de polling del panel ya en línea. Esa aserción (`"<script" not in pagina`) pertenece al
      reporte de cuarentena y **no se copia** al panel, que sí lleva script. Confirmar además que
      `pyproject.toml` no ganó ninguna dependencia nueva.
- [ ] 10.8 RED: test que confirma que `GET /panel/{id_corrida}` sirve HTML con el primer pintado ya
      con números, sin depender de que corra ningún `fetch`.
- [ ] 10.9 GREEN: agregar la ruta `GET /panel/{id_corrida}` en `rutas_corridas.py`, sirviendo
      `plantilla_panel` con el embudo ya calculado en el primer response; hereda la guarda de 9.11
      para el caso sin motor configurado.
- [ ] 10.10 RED: en `tests/scripts/test_servir_panel.py`, test que confirma que
      `scripts/servir_panel.py` levanta un `wsgiref.simple_server` con
      `socketserver.ThreadingMixIn` y responde a una petición real.
- [ ] 10.11 GREEN: crear `scripts/servir_panel.py` con el punto de entrada WSGI del diseño.
- [ ] 10.12 REFACTOR: `pytest tests/web/` completo en verde; `pytest` completo del repositorio en
      verde; confirmar en `apply-progress.md` que `pyproject.toml` no cambió.

---

## Pronóstico de carga de revisión

| Campo | Valor |
|---|---|
| Líneas estimadas | ~1.730 (5 tramos, ver tabla de tramos arriba) |
| Riesgo de presupuesto 400 líneas | High (Tramo 2 solo ya estimado en ~410) |
| PRs encadenados recomendados | Yes |
| División sugerida | PR1 (Tramo 1: Fases 1-3) → PR2 (Tramo 2: Fases 4-6) → PR3 (Tramo 3: Fase 7) → PR4 (Tramo 4: Fases 8-9) → PR5 (Tramo 5: Fase 10) |
| Delivery strategy | `auto-chain` |
| Chain strategy | `stacked-to-main` |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Tramos mapeados a PRs

| Tramo | Fases | PR | Base | Notas |
|---|---|---|---|---|
| 1 — Esquema e idempotencia | 1, 2, 3 | PR1 | `main` | No toca ninguna pantalla — ver ADVERTENCIA arriba |
| 2 — Propagación e inventario | 4, 5, 6 | PR2 | `main` (tras mergear PR1) | Dependencia dura de PR1; el más grande, considerar partir `scripts/procesar_carpeta.py` (6.8-6.9) en PR2.5 si se acerca a 450 líneas reales |
| 3 — Observabilidad | 7 | PR3 | `main` (tras mergear PR2) | Independiente de 4 y 5; podría adelantarse antes de PR2 si conviene por calendario |
| 4 — Modelo de lectura y JSON | 8, 9 | PR4 | `main` (tras mergear PR2 y PR3) | Depende de PR2 (necesita atribución); incluye el centinela de solapamiento completo y el orden de despacho |
| 5 — Pantalla y punto de entrada | 10 | PR5 | `main` (tras mergear PR4) | Depende de PR4; primer PR con algo visible en pantalla |

Con `auto-chain`, `sdd-apply` implementa el Tramo 1 (PR1) como el próximo tramo autónomo: inicio,
fin, verificación y frontera de reversión ya quedaron fijados arriba. No hace falta decisión del
usuario antes de empezar.
