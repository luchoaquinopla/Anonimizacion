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
| 2 | `pytest tests/pipeline/ tests/ingesta/ tests/integracion/test_reprocesar_no_duplica.py` | El centinela de partición total pasa de rojo a verde; el script produce una corrida con inventario; `estudio`/`cuarentena` quedan atribuidas, sobretamaño incluido |
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

- [ ] 1.1 RED: en `tests/dominio/test_modelos.py`, test que instancia `RegistroAnonimizado` con
      `corrida_id: str | None` y falla porque el campo no existe.
- [ ] 1.2 RED: test que confirma que `RegistroAnonimizado()` sin `corrida_id` sigue construyéndose
      (default `None`) — no rompe fixtures de otras fases.
- [ ] 1.3 GREEN: agregar `corrida_id: str | None = None` al final de `RegistroAnonimizado`
      (`dominio/modelos.py`).
- [ ] 1.4 RED: en `tests/dominio/test_errores.py`, test que instancia `ErrorDocumento` con
      `corrida_id: str | None` y falla porque el campo no existe.
- [ ] 1.5 GREEN: agregar `corrida_id: str | None = None` al final de `ErrorDocumento`
      (`dominio/errores.py`).
- [ ] 1.6 REFACTOR: `pytest tests/dominio/ tests/salida/ tests/pipeline/` en verde — confirmar que
      ningún llamador existente usa argumentos posicionales que el campo nuevo (al final, con
      default) pudiera romper.

## Fase 2 (Tramo 1): migración `0008_corrida_en_salida`

- [ ] 2.1 RED: en `tests/salida/test_migraciones.py`, test que corre `upgrade()` hasta `head` sobre
      SQLite en memoria y falla porque `0008` no existe (o las columnas/índices esperados no
      calzan).
- [ ] 2.2 RED: test que prepara `cuarentena` con dos filas duplicadas de `id_documento`
      preexistentes (`corrida_id` ausente) **antes** de `upgrade()` — fija el punto de partida: hay
      duplicados previos sin corrida en el sistema real.
- [ ] 2.3 GREEN: crear `migrations/versions/0008_corrida_en_salida.py`,
      `down_revision = "0007_clave_documento"`. `upgrade()`: `op.batch_alter_table("estudio")` →
      `add_column("corrida_id", String(36), nullable=True)` +
      `add_column("creado_en", DateTime(timezone=True), nullable=True)` +
      `create_index("ix_estudio_corrida_creado", ["corrida_id", "creado_en"])`;
      `op.batch_alter_table("cuarentena")` → `add_column("corrida_id", String(36), nullable=True)`
      + `create_unique_constraint("uq_cuarentena_corrida_documento", ["corrida_id", "id_documento"])`
      + `create_index("ix_cuarentena_corrida_creado", ["corrida_id", "creado_en"])`;
      `drop_index("ix_documento_corrida_corrida_id")`. `batch_alter_table` obligatorio: SQLite no
      soporta agregar `UNIQUE` con `ALTER TABLE` directo.
- [ ] 2.4 GREEN: confirmar que las dos filas duplicadas de 2.2 **siguen existiendo** tras
      `upgrade()` — la restricción única se crea sobre duplicados preexistentes sin deduplicar ni
      rellenar nada (los `NULL` no colisionan entre sí).
- [ ] 2.5 RED: test de `downgrade()` — `upgrade()` seguido de `downgrade()` sobre SQLite en memoria
      confirma que el esquema vuelve al estado de `0007` (columnas e índices nuevos fuera).
- [ ] 2.6 GREEN: `downgrade()` — inverso simétrico de 2.3 sobre `cuarentena` y `estudio`.
- [ ] 2.7 REFACTOR: correr `upgrade`/`downgrade`/`upgrade` para confirmar idempotencia estructural,
      mismo patrón que `0007`.

## Fase 3 (Tramo 1): `EscritorCuarentena` — idempotencia y el bug de conteo doble YA MERGEADO

- [ ] 3.1 RED — reproduce el defecto antes de arreglarlo (código ya mergeado): en
      `tests/web/test_reporte_cuarentena.py`, dos llamadas a `EscritorCuarentena.registrar` con el
      **mismo** `ErrorDocumento(id_documento=...)` contra el esquema y el código **actuales** (sin
      guarda) dejan dos filas en `cuarentena`, y `construir_reporte` las cuenta dos veces. Este
      test debe estar en rojo (es decir, confirmar la duplicación) antes de aplicar 3.5.
- [ ] 3.2 GREEN (esquema): en `salida/modelos_orm.py`, agregar `corrida_id: Mapped[str | None]` y
      `creado_en: Mapped[datetime | None]` a `Estudio`; `corrida_id: Mapped[str | None]` a
      `Cuarentena` con `UniqueConstraint("corrida_id", "id_documento", name="uq_cuarentena_corrida_documento")`
      en `__table_args__` — debe coincidir exactamente con la migración de 2.3.
- [ ] 3.3 RED: test que inserta dos filas `Cuarentena` con el mismo `(corrida_id, id_documento)`
      directo contra SQLite en memoria y confirma `IntegrityError`.
- [ ] 3.4 RED: test que confirma que dos filas `Cuarentena` con `corrida_id=None` **no** colisionan
      entre sí aunque compartan `id_documento` — las filas legadas y los fixtures sin corrida
      siguen sin garantía.
- [ ] 3.5 GREEN: en `EscritorCuarentena.registrar` (`salida/cuarentena.py`), guarda de dos capas
      calcada de `escribir_registro`: dentro de `sesion.begin()`, `SELECT` previo por
      `(corrida_id, id_documento)` si `error.corrida_id is not None` — si ya existe, retornar sin
      escribir; envolver el `add`/flush en `try/except IntegrityError: pass`. Propagar
      `corrida_id=error.corrida_id` al construir `Cuarentena(...)`.
- [ ] 3.6 GREEN: confirmar que 3.1 pasa a verde — registrar dos veces el mismo error con
      `corrida_id` fija deja una sola fila y `construir_reporte` cuenta una vez.
- [ ] 3.7 RED: test que registra el mismo `id_documento` bajo dos `corrida_id` distintas y confirma
      que quedan **dos** filas — historial entre corridas, no duplicado.
- [ ] 3.8 RED: test de concurrencia — dos registros del mismo `(corrida_id, id_documento)` sin que
      el primero haya comiteado (dos sesiones contra el mismo engine SQLite, o mock de sesión)
      confirma que la segunda captura `IntegrityError` sin propagar.
- [ ] 3.9 REFACTOR: `pytest tests/salida/ tests/web/test_reporte_cuarentena.py` en verde; actualizar
      el docstring de `EscritorCuarentena.registrar` para describir la guarda nueva.

## Fase 4 (Tramo 2): partición total del lote (Decisión 6)

- [ ] 4.1 RED: en `tests/pipeline/test_particion_total_del_lote.py` (nuevo), coordinador de
      episodios falso que devuelve un episodio en `episodios_pendientes` no vacío; correr
      `procesar_lote` y afirmar `len(resultados) == len(items)` — **rojo hoy**: los pendientes se
      pierden en silencio.
- [ ] 4.2 RED: segundo test en el mismo archivo — el caso normal (sin pendientes) también cumple
      `len(resultados) == len(items)`.
- [ ] 4.3 GREEN: en `pipeline/ejecutor.py`, nombrar `_GRUPO_ES_UNIDAD_COMPLETA = True` (reemplaza el
      `True` anónimo de la línea ~366) con el comentario de la invariante; `_coordinar_resueltos`
      lanza `RuntimeError` si algún resuelto no cae ni en aprobados ni en cuarentena.
- [ ] 4.4 REFACTOR: `pytest tests/pipeline/` en verde; confirmar que `_GRUPO_ES_UNIDAD_COMPLETA` NO
      se expone como parámetro público — exponerla sin la contabilidad detrás es ofrecer la trampa
      con una perilla.

## Fase 5 (Tramo 2): `corrida_id` viaja por `procesar_lote`/`procesar_grupo`

- [ ] 5.1 RED: extender el centinela de claves exactas de `procesar_grupo` — la referencia por
      documento sigue teniendo **exactamente** `{id_documento, uri, sha256}` aunque
      `procesar_grupo` reciba `corrida_id` como parámetro hermano del lote.
- [ ] 5.2 RED: test que llama `EjecutorPipeline.procesar_lote(items, corrida_id="c1")` y confirma
      que el `RegistroAnonimizado` emitido trae `corrida_id == "c1"`.
- [ ] 5.3 RED: test equivalente para el camino de fallo — un ítem apartado produce un
      `ErrorDocumento` con `corrida_id == "c1"`.
- [ ] 5.4 GREEN: agregar `corrida_id: str | None = None` a `procesar_lote`; copiarlo en `_emitir`
      (a `RegistroAnonimizado`) y en `_a_fallo` (a `ErrorDocumento`); agregar
      `corrida_id: str` a `procesar_grupo(corrida_id, referencias)` y propagarlo a `procesar_lote`
      sin tocar la construcción de `ItemLote`.
- [ ] 5.5 REFACTOR: `pytest tests/pipeline/` en verde; confirmar por lectura que ningún módulo del
      núcleo importa `RepositorioCorridas` ni consulta la tabla `corrida`.

## Fase 6 (Tramo 2): inventario — `registrar_documentos`, `LanzadorCorrida`, `CuarentenaDeCorrida`

- [ ] 6.1 RED: en `tests/ingesta/test_repositorio_corridas.py`, test que llama
      `RepositorioCorridas.registrar_documentos(documentos, tamano_lote=1000)` y falla porque el
      método no existe.
- [ ] 6.2 GREEN: agregar `registrar_documentos(documentos, *, tamano_lote=1000) -> int` a
      `RepositorioCorridas` — una sesión por lote de `tamano_lote`, misma guarda de idempotencia
      por `(corrida_id, huella_contenido)` que `registrar_documento`, que se conserva sin cambios.
- [ ] 6.3 RED: test que llama `registrar_documentos` dos veces con el mismo lote (misma corrida) y
      confirma que `uq_documento_corrida_huella` evita duplicar el denominador.
- [ ] 6.4 RED: en `tests/ingesta/test_lanzador_corrida.py` (nuevo), test que llama
      `LanzadorCorrida.lanzar(ruta)` y confirma `corrida_id` + referencias devueltos, con la
      corrida avanzada `CREADA → INVENTARIANDO → PROCESANDO` — falla porque `LanzadorCorrida` no
      existe.
- [ ] 6.5 GREEN: crear `ingesta/lanzador_corrida.py` con `LanzadorCorrida`: crea la `Corrida`,
      avanza a `INVENTARIANDO`, llama `fuente.listar()` con el sumidero decorado, llama
      `registrar_documentos(...)`, avanza a `PROCESANDO`, devuelve `corrida_id` + referencias.
- [ ] 6.6 RED: test que confirma que un artefacto apartado por sobretamaño en `FuenteLocal` (antes
      de calcular su huella) llega a cuarentena con el `corrida_id` correcto — falla porque
      `CuarentenaDeCorrida` no existe.
- [ ] 6.7 GREEN: crear `CuarentenaDeCorrida` (dataclass frozen que envuelve un `SumideroCuarentena`
      y estampa `corrida_id` en cada `ErrorDocumento` vía `replace()` antes de delegar) en
      `ingesta/lanzador_corrida.py`; `LanzadorCorrida` arma la fuente de enumeración con este
      sumidero.
- [ ] 6.8 RED: en `tests/scripts/test_procesar_carpeta.py`, test que confirma que
      `scripts/procesar_carpeta.py` usa `LanzadorCorrida` y propaga `corrida_id` hasta
      `procesar_grupo` — falla porque el script no lo hace todavía.
- [ ] 6.9 GREEN: modificar `scripts/procesar_carpeta.py` para usar `LanzadorCorrida` y pasar
      `corrida_id` a `procesar_grupo`.
- [ ] 6.10 RED: extender `tests/integracion/test_reprocesar_no_duplica.py` a cuarentena — reprocesar
      el mismo grupo no aumenta el conteo de filas en `cuarentena` de esa corrida (spec
      `escritura-idempotente` delta, "reprocesar la misma corrida no duplica el apartado").
- [ ] 6.11 GREEN: ajustes de wiring residuales si 6.10 los revela (no debería requerir lógica nueva
      si 3.5 y 5.4 están completas).
- [ ] 6.12 REFACTOR: `pytest tests/ingesta/ tests/pipeline/ tests/integracion/test_reprocesar_no_duplica.py`
      en verde.

## Fase 7 (Tramo 3): observabilidad cableada en la raíz de composición (Decisión 7)

- [ ] 7.1 RED — `test_la_fabrica_cablea_la_observabilidad`: espía de `ColectorMetricas`/
      `BitacoraSegura` inyectado vía `construir_fabrica_ejecutor(metricas=, bitacora=)`, procesar
      un grupo real de tres PDFs por `tareas.procesar_grupo` (mismo molde que
      `tests/integracion/test_wiring_produccion.py`) y confirmar que el espía recibió
      observaciones — falla porque los parámetros no existen todavía.
- [ ] 7.2 GREEN: agregar `metricas: ColectorMetricas | None = None` y
      `bitacora: BitacoraSegura | None = None` a `construir_fabrica_ejecutor`, con la semántica de
      `dormir`/`resolver_claves` (`None` = producción); cablear dentro de `_fabrica()`.
- [ ] 7.3 RED — `test_sin_inyeccion_explicita_igual_hay_colector`: construir el ejecutor SIN pasar
      nada e introspeccionar que trae un colector/bitácora reales, no `None`.
- [ ] 7.4 GREEN: confirmar/ajustar el default de producción dentro de `_fabrica()` si 7.3 lo exige.
- [ ] 7.5 RED — `test_un_colector_que_explota_no_tumba_el_grupo`: colector que lanza excepción en
      todos sus métodos, procesar un grupo real de tres PDFs y confirmar que los tres se publican
      igual (invariante 3 de la propuesta).
- [ ] 7.6 GREEN: crear `_observar_sin_romper` en `pipeline/ejecutor.py`; envolver con él
      `incrementar_documento_procesado` (`_emitir`), `incrementar_fallo` (`_a_fallo`), y
      `observar_duracion_ms` (parámetro nuevo `observar: Callable[[str, float], None] | None = None`
      en `_ejecutar_con_reintentos`).
- [ ] 7.7 RED: test que confirma que `bitacora.registrar(resultado.resumen_trazable())` se llama
      exactamente una vez por resultado al cerrar `procesar_lote`.
- [ ] 7.8 GREEN: agregar esa llamada al cierre de `procesar_lote`, envuelta también en
      `_observar_sin_romper`.
- [ ] 7.9 REFACTOR: `pytest tests/pipeline/` en verde; correr los ensayos de carga de mil y diez mil
      y confirmar que el tiempo por documento no se degrada frente a la última corrida validada
      (referencia: `openspec/changes/escritura-idempotente/tasks.md`, Fase 12).

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
