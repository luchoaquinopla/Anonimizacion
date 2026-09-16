# Tareas: auditoría y poda

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | PR0 ~420 · PR1 ~180 · PR2 ~220 · PR3 ~300 (split 3a/3b si excede) · PR4a ~250 · PR4b ~200 · PR5 ~350 · PR6a-e dentro de presupuesto · PR6f ~800 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | Ver "Suggested Work Units" abajo (`feature-branch-chain`, ya decidido en design.md D7) |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

**Excepciones ya fijadas en `design.md` (no requieren nueva decisión)**: PR0 y PR6f usan
`size:exception` — PR0 porque partir la red de seguridad la deja parcialmente tejida antes
de que PR1 la necesite entera; PR6f porque es borrado puro de prosa verificado por la
compuerta AST (mecanismo más fuerte que el límite de líneas).

### Suggested Work Units

| Unit | Goal | Base branch | Notes |
|---|---|---|---|
| PR0 | E0 — red de caracterización, no toca `src/` | `feat/auditoria-y-poda` (tracker, draft) | `size:exception` |
| PR1 | E1 — trampas de extensión (3 defectos) | PR0 | ~180 |
| PR2 | E2 — vocabulario único de etapas | PR1 | ~220 |
| PR3(a/b) | E3 — poder de detección en tests | PR2 | split si >400 |
| PR4 | E4 — mudanza de `procesar` y `servir` a `comandos/` | PR3 | `git mv` en commit propio, separado de las ediciones. `size:exception` |
| PR5 | E5 — retiro Celery/Redis + métricas muertas | PR4 | incluye doc de deploy |
| PR6a | E6 — migración de los 8 invariantes a Obsidian + compuerta AST | PR5 | **requiere aprobación del usuario antes de escribir en el vault** |
| PR6b | E6 — poda de prosa (todas las capas) | PR6a | `size:exception`; protegido por la compuerta AST |
| Higiene | Archivar `correccion-orientacion-senal-ecg/` | `main` (fuera de la cadena) | PR independiente |

**Nota (no es tarea de este cambio)**: `tests/integracion/test_postgres_carrera_real.py:98`
hace `drop_all` sobre la base compartida del 5433. Las fixtures nuevas de E0 (crear/destruir
su propia base) evitan ese patrón; el archivo existente **no se toca** acá.

---

## Fase 0 — Entrega 0: red de seguridad (PR0, no toca `src/`)

- [x] 0.1 Agregar marcador `caracterizacion` en `pyproject.toml [tool.pytest.ini_options]`.
- [x] 0.2 `tests/caracterizacion/conftest.py`: fixture que crea `caracterizacion_<uuid>` en
      AUTOCOMMIT contra Postgres 5433, la destruye en `finally`, `pytest.skip` sin servidor.
- [x] 0.3 Escribir `test_pipeline_punta_a_punta.py` (Requisito 1): corpus sintético con
      episodio completo/incompleto/ambiguo/cuarentena, fija filas y registro de salida. Verde.
- [x] 0.4 Romper a propósito la reconciliación (aprobar campo sin evidencia); confirmar rojo;
      pegar evidencia en el PR; restaurar el código. Evidencia (corregida tras revisión del
      orquestador -- ver apply-progress "Corrección post-revisión"): nuevo test
      `test_un_vent_rate_publicado_sin_evidencia_real_hoy_se_aparta_por_valor_discrepante`
      en `test_pipeline_punta_a_punta.py`. Corpus: laboratorio (puente de identidad) + ECG en
      el mismo lote, con un `obtener_parseador` que corrompe `vent_rate` a `"160"` (el valor
      real de `PR interval`, sin evidencia real de ser `Vent. rate`) DESPUÉS de parsear, sin
      tocar `fuentes`. Hoy: el ECG se aparta con `VALOR_DISCREPANTE`/`reconciliacion`, ninguna
      fila en `medicion_ecg`. Mutando `_comun.py` (deshabilitando el chequeo de
      `validador_asociacion`): el ECG pasa a `ExitoDocumento` y `medicion_ecg` publica
      `vent_rate="160"` -- el propio test punta a punta se pone en ROJO. Revertido.
- [x] 0.5 Escribir `test_contrato_cli.py` (Requisito 2): banderas, defaults efectivos y
      códigos de salida por subcomando. Verde.
- [x] 0.6 Romper a propósito un código de salida de un subcomando; confirmar rojo; evidencia;
      restaurar. Evidencia: `test_diagnosticar_devuelve_1_si_hay_un_hallazgo_en_falta` en rojo.
- [x] 0.7 Escribir `test_codigos_cuarentena.py` (Requisito 3): pares entrada→(código, etapa).
      Verde.
- [x] 0.8 Romper a propósito la etapa de un código; confirmar rojo; evidencia; restaurar.
      Evidencia: los tests de `episodio_incompleto`/`episodio_ambiguo` en rojo.
- [x] 0.9 Escribir `test_embudo.py` (Requisito 4), fixture reutilizable literal para E2. Verde.
- [x] 0.10 Romper a propósito una etapa del cálculo del embudo (ej. quitar `"despacho"`);
      confirmar rojo; evidencia; restaurar. Evidencia: ambos tests de `test_embudo.py` en rojo.
- [x] 0.11 Escribir `test_reporte_corrida.py` (Requisito 5) sobre `MetricasDespacho`. Verde.
- [x] 0.12 Romper a propósito la lectura de `MetricasDespacho` en el reporte; confirmar rojo;
      evidencia; restaurar. Evidencia: `test_reporte_de_recuperacion_con_resultados_mixtos`
      en rojo.
- [x] 0.13 Verificación PR0: `git diff feat/auditoria-y-poda --stat -- src/` vacío;
      `uv run pytest -q -m caracterizacion` verde (16/16); las 5 evidencias de rojo
      documentadas en apply-progress (Engram `sdd/auditoria-y-poda/apply-progress`).

## Fase 1 — Entrega 1: trampas de extensión (PR1)

- [x] 1.1 RED — `tests/salida/destinos/test_postgres.py` (el archivo real es
      `destinos/test_postgres.py`, no `test_destinos_postgres.py`): 4to tipo simulado
      (`_TipoDocumentoDePrueba.RESONANCIA_MAGNETICA`, `str, Enum` propio -- ver 1.1-nota más
      abajo) llamando a `_insertar` directo (bypasea la whitelist de `escribir_registro`, que
      hoy sí rechaza tipos desconocidos). RED confirmado en commit `cafaf51` contra
      `postgres.py` sin modificar: `Failed: DID NOT RAISE Exception` (cae al `else` mudo y
      escribe en `medicion_eco`) y `AttributeError: 'EscritorPostgres' object has no attribute
      '_escritores_por_tipo'` (Escenario 2).
- [x] 1.2 GREEN — commit `962fd0d`: `_escritores_por_tipo` (dict de instancia, no de módulo)
      único para whitelist y despacho en `postgres.py`; `ValueError` explícito en
      `escribir_registro` (mismo mensaje de siempre) o `KeyError` si se llega a `_insertar` sin
      pasar esa guarda.
- [x] 1.3 RED — `tests/pipeline/test_coordinador_episodios.py`: episodio con los 3 tipos
      requeridos + un 4to tipo simulado no requerido. RED confirmado en commit `a1ffed5` contra
      `coordinador_episodios.py` sin modificar: `AssertionError: assert 0 == 1` (cae en
      `ESTUDIOS_FALTANTES` por `set() !=`) y `TypeError: ...__init__() got an unexpected
      keyword argument 'tipos_requeridos'`.
- [x] 1.4 GREEN — commit `18011f7`: `CoordinadorEpisodios.__init__(pepper, tipos_requeridos=
      _TIPOS_REQUERIDOS_DEFAULT)`; comparación `self._tipos_requeridos - set(tipos)` en
      `coordinador_episodios.py`; `coordinar_episodios(...)` (función módulo) gana el mismo
      parámetro con idéntico default, sin romper a `pipeline/ejecutor.py` ni a los tests
      preexistentes que no lo pasan.
- [x] 1.5 RED — `tests/salida/test_constructor_registro.py`: 4to tipo sin constructor
      registrado. **Hallazgo de diseño (no es RED)**: el Escenario 1 ("sin constructor ->
      excepción explícita") YA pasa hoy -- `construir_registro` ya termina en `else: raise
      ValueError(...)` nombrando el tipo (design.md D1 lo documenta: este defecto es de
      idioma/consistencia, no de falla silenciosa). El RED real es el Escenario 2 ("con
      constructor registrado construye su registro"): hoy no existe ningún punto de extensión
      para registrar un constructor sin editar la cadena `if/elif`. RED confirmado en commit
      `ba3db52` contra `constructor_registro.py` sin modificar: `AttributeError: module
      '...constructor_registro' has no attribute '_CONSTRUCTORES_POR_TIPO'`.
- [x] 1.6 GREEN — commit `4d4cf18`: registry `_CONSTRUCTORES_POR_TIPO` (mismo idioma que
      `parseo/registro.py` y `reconciliacion/registro.py`); `construir_registro` preserva
      `ValueError` (no `KeyError` crudo) si el tipo no tiene constructor.
- [x] 1.7 Acta de una línea (única divergencia semántica declarada de toda la cadena,
      design.md D1): **"un episodio con los 3 tipos requeridos más un 4to tipo deja de caer en
      ESTUDIOS_FALTANTES"**. Ningún otro comportamiento observable cambió -- confirmado por
      `tests/caracterizacion/` sin modificar y en verde (1.8).
- [x] 1.8 Verificación PR1: 1.1/1.3/1.5 confirmados en rojo en su commit respectivo (ver
      evidencia arriba, y el reporte de `sdd-apply` para el detalle completo);
      `uv run pytest -q -m "not postgres"` → 1026 passed, 1 skipped (symlink no soportado en
      Windows, preexistente), 1 failed (`test_despachar_en_paralelo_..._distintos`,
      PRE-EXISTENTE y sensible a la carga, confirmado en E0 -- no es de esta entrega);
      `uv run pytest -q -m postgres` → 28 passed (sin cambios respecto a E0, ninguna prueba
      nueva de esta entrega toca Postgres real); `tests/caracterizacion/` → 17 passed sin
      modificarse (`git diff feat/auditoria-y-poda --stat -- tests/caracterizacion/` vacío);
      `ruff check .` → All checks passed. Tamaño real (a la fecha de esta verificación, antes
      de 1.9/1.10): `git diff feat/auditoria-y-poda --numstat` → 274 líneas insertadas, 32
      borradas.
- [x] 1.9 RED — 4to defecto de la misma clase, encontrado en revisión adversarial y verificado
      por el orquestador (fuera del alcance original de `tasks.md`, incorporado a esta entrega
      porque `proposal.md` excluyó `exportacion.py` sólo para lógica NUEVA por tipo, no para
      este patrón de despacho): `salida/exportacion.py::_procesar_pagina:359-370` despachaba
      por `if/elif/else` -- cualquier `tipo_documento` que no fuera "ecg"/"laboratorio" caía en
      el `else` mudo y se exportaba como fila de `eco.parquet`, con `mediciones_eco.get()`
      devolviendo `None` -- más grave que en `postgres.py`: contamina en silencio el DATASET
      que consume el modelo, no una tabla intermedia. `tests/salida/test_exportacion.py`: 4to
      tipo simulado (`_TipoDocumentoDePrueba.RESONANCIA_MAGNETICA.value`, mismo mecanismo
      `str, Enum` ya validado -- acá basta el `.value` porque `Estudio.tipo_documento` es
      `String`, no un enum de SQLAlchemy). RED confirmado en commit `78f29dc` contra
      `exportacion.py` sin modificar: `Failed: DID NOT RAISE Exception` (la fila se exportó
      silenciosamente a `eco.parquet`).
- [x] 1.10 GREEN — commit `61deb90`: `_PROCESADORES_POR_TIPO` (dict `TipoDocumento.value ->
      función`) unifica whitelist y despacho, mismo patrón que `postgres.py`; tipo sin entrada
      levanta `ValueError` explícito. Se compara contra `TipoDocumento.X.value` (fuente única
      del vocabulario, `dominio/tipos_documento.py`), no contra literales sueltos como antes
      ("ecg"/"laboratorio"). `tiene_tipo`/columnas `tiene_*` conservan sus claves cortas
      ("eco", no "ecocardiograma") vía `_CLAVE_TIENE_TIPO_POR_TIPO` -- son nombres de columna
      Parquet ya publicados (`ESQUEMA_EPISODIOS`), no vocabulario a unificar en esta entrega
      (eso es E2). Verificado sin regresión: `tests/salida/test_esquema_arrow_de_exportacion.py`
      y `tests/pii/test_auditoria_exportacion_sin_pii.py` siguen en verde sin modificarse.
      Tamaño final real (incluye 1.9/1.10): `git diff feat/auditoria-y-poda --numstat` → 443
      líneas insertadas, 62 borradas, 9 archivos. `uv run pytest -q -m "not postgres"` → 1027
      passed, 1 skipped (mismo symlink preexistente), 1 failed (mismo
      `test_despachar_en_paralelo_..._distintos`, confirmado ES el mismo fallo sensible a la
      carga, no uno nuevo); `-m postgres` → 28 passed (sin cambios); `-m caracterizacion` → 17
      passed, `git diff feat/auditoria-y-poda --stat -- tests/caracterizacion/` vacío; `ruff
      check .` → All checks passed.

## Fase 2 — Entrega 2: vocabulario único de etapas (PR2)

- [x] 2.1 RED — `tests/pipeline/test_vocabulario_de_etapas.py`: recorre `src/` con `ast`,
      afirma todo `_ETAPA` ∈ enum unificado y `EtapaDocumento ⊆ Etapa`. RED confirmado en
      commit `9a349ea` contra `pipeline/etapas.py` sin modificar:
      `AssertionError: assert {'despacho', ...} <= {'coordinacio...'}` (falta `DESPACHO` en
      `Etapa`). El test de `_ETAPA` sin correspondencia pasó desde el día 0 porque
      `"extraccion"`/`"parseo"` ya eran miembros de `Etapa` -- el RED real es el de subconjunto.
- [x] 2.2 GREEN — commit `25740d1`: `pipeline/etapas.py::Etapa` ampliado a 10 miembros
      (+ `DESPACHO`); `dominio/errores.py::EtapaDocumento` **no se toca** (confirmado:
      `git diff feat/auditoria-y-poda -- src/anonimizacion/dominio/errores.py` vacío).
- [x] 2.3 RED — `tests/web/test_embudo_orden.py`: afirma `ORDEN_EMBUDO`/`ETAPAS_EMBUDO`. RED
      confirmado en commit `049ad58` contra `web/embudo_corrida.py` sin modificar: `ImportError:
      cannot import name 'ORDEN_EMBUDO'` (seguía siendo lista de strings independiente).
- [x] 2.4 GREEN — commit `099be04`: `ORDEN_EMBUDO: tuple[Etapa, ...]` explícito (orden verbatim
      de D4) y `ETAPAS_EMBUDO = tuple(e.value for e in ORDEN_EMBUDO)`. Corrección propia
      (commit `dc89d32`): la lista de exclusión de 2.6 se había agregado por adelantado junto
      con este GREEN; se retiró para respetar el ciclo RED/GREEN separado de 2.5/2.6.
- [x] 2.5 RED — `tests/web/test_embudo_cobertura_desglose.py`: todo miembro de `EtapaDocumento`
      ∈ `ORDEN_EMBUDO` o en `ETAPAS_EXCLUIDAS_DEL_EMBUDO` con motivo. RED confirmado en commit
      `1048e38` contra `web/embudo_corrida.py` sin modificar: `ImportError: cannot import name
      'ETAPAS_EXCLUIDAS_DEL_EMBUDO'`.
- [x] 2.6 GREEN — commit `f989277`: `ETAPAS_EXCLUIDAS_DEL_EMBUDO = (Etapa.DETECCION,
      Etapa.DETECCION_PII)` con comentario de motivo en `web/embudo_corrida.py`.
- [x] 2.7 Verificación PR2: `tests/caracterizacion/test_embudo.py` (0.9/0.10 de E0) sigue
      pasando **sin modificarse** -- `git diff feat/auditoria-y-poda --stat --
      tests/caracterizacion/` vacío, `-m caracterizacion` → 17 passed. `ruff check .` → All
      checks passed. `uv run pytest -q -m "not postgres"` → 1032 passed, 1 skipped (symlink
      Windows, preexistente), 1 failed (`test_despachar_en_paralelo_..._distintos`, confirmado
      EL MISMO fallo preexistente sensible a la carga de E0/E1, no uno nuevo). `-m postgres` →
      28 passed (sin cambios respecto a E1).

## Fase 3 — Entrega 3: poder de detección en tests (PR3, split a/b si >400)

- [x] 3.1 Agregar aserciones reales sobre el valor de retorno de `reconciliar(...)` en los 31
      tests sin oráculo de `tests/reconciliacion/` (ej. `test_ecg_mortara.py:57,77`):
      `assert == ()` en aprobados, tupla exacta esperada en degradación. Commit `2c7ffa7`.
      Valor exacto de cada aserción determinado ejecutando el caso real (nunca derivado dentro
      del propio `assert`); confirmado por lectura del contrato en `reconciliacion/base.py` y
      `reconciliacion/_comun.py`. Casos ECG sin `senal` inyectada devuelven `("ecg.senal",)`,
      no `()` (`ecg_mortara.py:175-176`). `uv run python -c "..."` con conteo por `ast`
      (ver 3.8) confirma **cero** tests de `tests/reconciliacion/` sin `assert`/`pytest.raises`
      sobre el retorno de `reconciliar(...)` tras este batch.
- [x] 3.2 Demostrar manualmente (sin commitear la mutación) que 3.1 detecta una degradación
      simulada del parser; documentar en el PR. Evidencia: `parseo/ecg_mortara.py:349` mutado
      a `pr_interval=None` fijo (degradación simulada: el parser deja de citar un campo que el
      PDF sí trae); `uv run pytest -q tests/reconciliacion/` → 1 failed
      (`test_inventario_ecg_cubre_el_modelo_generado_por_el_parseador`,
      `AssertionError: ('ecg.pr_interval', 'ecg.senal') == ('ecg.senal',)`), 111 passed.
      Revertido con `git checkout -- src/anonimizacion/parseo/ecg_mortara.py`;
      `git status --porcelain -- src/` vacío tras revertir.
- [x] 3.3 RED — `tests/web/test_codigos_cuarentena_exhaustividad.py`:
      `{CodigoErrorDocumento} - {CAMPO_NO_EXTRAIDO} ⊆ EXPLICACION_POR_CODIGO.keys()`. Commit
      `fd003d7`. RED demostrado por mutación (no había hueco real que forzara un RED contra
      `main`): entrada `"pdf_ilegible"` retirada a propósito de
      `web/codigos_cuarentena.py::EXPLICACION_POR_CODIGO`; `uv run pytest -q
      tests/web/test_codigos_cuarentena_exhaustividad.py` → 1 failed,
      `AssertionError: ... sin entrada en EXPLICACION_POR_CODIGO: {'pdf_ilegible'}`. Revertido
      con `git checkout --`; `git status --porcelain -- src/` vacío.
- [x] 3.4 GREEN — completar entradas faltantes en `web/codigos_cuarentena.py`
      `EXPLICACION_POR_CODIGO` si 3.3 detecta huecos. **No aplica**: verificado con
      `{c.value for c in CodigoErrorDocumento} - {"campo_no_extraido"} -
      EXPLICACION_POR_CODIGO.keys()` → `set()` vacío contra `main` sin modificar (18 códigos,
      los 17 no excluidos ya tienen entrada). El test queda como red permanente contra futuros
      códigos sin traducción; no se tocó `src/` en esta tarea.
- [x] 3.5 Renombrar `tests/pipeline/test_equivalencia_agrupacion.py` →
      `tests/pseudonimizacion/test_ventana_de_episodio.py`; eliminar comparación tautológica
      y el helper `_episodios_del_coordinador`/`_pares`. Commit `240cc49` (`git mv` + reescritura
      de contenido).
- [x] 3.6 Reexpresar los 3 oráculos existentes sobre `vincular_episodios` directo; agregar
      oráculos nuevos a mano (7 días exacto antes del ancla, dos anclas separadas por meses,
      episodio de un solo documento) con asserts sobre `metadata_por_episodio[...].fecha_ancla`.
      Commit `240cc49`. RED confirmado por mutación (`vinculacion.py:100`, umbral de ventana
      forzado de `_VENTANA_DIAS` a `999`): 3/6 tests del archivo nuevo se ponen en rojo
      (`test_siete_dias_entra_ocho_corta_el_episodio`,
      `test_saltos_encadenados_de_seis_dias_no_se_funden_en_un_episodio_de_doce`,
      `test_dos_anclas_del_mismo_paciente_separadas_por_meses`) -- confirma que el oráculo
      nuevo detecta una regresión real de agrupación, a diferencia del espejo que reemplaza.
      Revertido con `git checkout --`; `git status --porcelain -- src/` vacío.
- [x] 3.7 GREEN — corregir docstring `coordinador_episodios.py:9-13`: ya no afirma que el test
      "fija esa equivalencia como contrato". Commit `240cc49` (mismo commit que 3.5/3.6 por ser
      la misma unidad de trabajo: D5 exige que el reemplazo del test y la corrección del
      docstring vayan juntos).
- [x] 3.8 Verificación PR3: suite completa verde. `uv run pytest -q -m "not postgres"` →
      1035 passed, 1 skipped (symlink Windows, preexistente), 1 failed
      (`test_despachar_en_paralelo_..._distintos`, confirmado EL MISMO fallo preexistente
      sensible a la carga, no uno nuevo). `-m postgres` → 28 passed. `-m caracterizacion` →
      17 passed; `git diff feat/auditoria-y-poda --stat -- tests/caracterizacion/` vacío.
      `ruff check .` → All checks passed. No superó 400 líneas (ver tamaño real en
      apply-progress), no hizo falta partir en PR3a/PR3b.

## Fase 4 — Entrega 4: CLI instalable por wheel (PR4, consolidado desde PR4a/PR4b)

- [x] 4.0 (no en el plan original, prerrequisito bloqueante) — commit `889a36d`: corregidos 2
      tests de `tests/caracterizacion/test_contrato_cli.py` (`test_procesar_sin_banderas_...`,
      `test_procesar_devuelve_1_sin_llegar_a_cargar_script_...`) que monkeypatcheaban
      `cli._cargar_script` y afirmaban sobre el `argv` armado para `sys.argv` -- el MECANISMO
      que esta entrega elimina, no la superficie observable que D1 de `design.md` exige y que
      el propio docstring del archivo ya declaraba (defecto de PR0, no visto por la revisión
      adversarial). Reescritos para afirmar sobre los valores efectivos de
      `ConfiguracionOperador` que llegan a `diagnosticar()` y sobre el código/mensaje de salida
      -- ningún assert depende de `_cargar_script`/`sys.argv`. RED confirmado por mutación
      (rompiendo `_resolver`/el corte temprano de `_comando_procesar`), revertido antes del
      commit. Los 7 tests del archivo siguen en verde.
- [x] 4.1 `tests/empaquetado/test_wheel_instalado.py` (commit `8d4866b`): fixture de sesión
      `uv build --wheel` + `uv venv --system-site-packages` + `uv pip install --no-deps`; test
      de guarda de honestidad (subproceso confirma `anonimizacion.__file__` y `shutil.which`
      dentro del venv efímero, ninguno en el checkout).
- [x] 4.2 Test estático de empaquetado: el wheel (inspeccionado por `zipfile`, no el `RECORD`)
      incluye `anonimizacion/comandos/procesar.py`/`servir.py` y ningún archivo bajo `scripts/`.
- [x] 4.3 RED — OBLIGATORIA: subproceso en el venv que stubea `diagnosticar` (hallazgos OK) y
      `cli.comandos_procesar.ejecutar` (stub retorna 0), llama
      `anonimizacion.cli.main(["procesar", ...])`; afirma código 0 y stub invocado 1 vez.
      Confirmado en ROJO contra el código anterior a esta entrega: wheel construido desde el
      commit `ad9521c` (worktree efímero), mismo mecanismo de venv, mismo subproceso sin
      mockear `comandos_procesar` (no existía) -- `FileNotFoundError` en `_cargar_script`
      buscando `scripts/procesar_carpeta.py` dentro del venv, exit code 1. Evidencia completa
      en Engram `sdd/auditoria-y-poda/apply-progress`.
- [x] 4.4 Marcador `empaquetado` agregado a `pyproject.toml`, incluido por defecto en
      `-m "not postgres"` (confirmado: 1039 tests seleccionados, 28 deselected = sólo postgres).
      Costo medido: 3 tests en ~5.3s (build ~1s, venv ~0.1s, install ~0.9s, subprocesos
      ~0.1-4s) -- bien por debajo del techo de ~45s de `design.md`.
- [x] 4.5 `git mv` puro (commit `a420c8e`, 0 líneas por `git diff -M --summary`, 100% rename):
      `scripts/procesar_carpeta.py` → `src/anonimizacion/comandos/procesar.py`;
      `scripts/servir_panel.py` → `src/anonimizacion/comandos/servir.py`;
      `tests/scripts/test_procesar_carpeta.py` → `tests/comandos/test_procesar.py`;
      `tests/scripts/test_servir_panel.py` → `tests/comandos/test_servir.py` (ambos módulos y
      ambos tests en el mismo commit de mudanza pura, per consolidación de PR4a/PR4b indicada
      por el orquestador).
- [x] 4.6 GREEN (commit `270f77e`) — `comandos/procesar.py`: quitado `_parsear_args`/
      `_tipo_procesos`/`main()` (el segundo `argparse`); importa `_DB_URL_DEFAULT` desde
      `configuracion.py`. `cli.py` reemplaza `_cargar_script`/`spec_from_file_location` por
      `from anonimizacion.comandos import procesar as comandos_procesar` +
      `comandos_procesar.ejecutar(...)` con argumentos con nombre; la composición que hacía
      `main()` (pepper, `MotorPii`, `construir_engine_postgres`) se mudó a
      `cli.py::_comando_procesar`. `_tipo_procesos` (validación del tope duro) se aplica una
      sola vez, en el `argparse` de `cli.py`, para `procesar` y `servir`.
- [x] 4.7 Adaptado `tests/comandos/test_procesar.py` (commit `270f77e`): `_cargar_script()` pasa
      a import normal; mismo cuerpo en los 12 tests que llaman `modulo.ejecutar(...)` directo
      (sin reescritura). El único test que ejercitaba `main()`
      (`test_main_usa_construir_engine_postgres_no_create_engine_pelado`) se retiró de este
      archivo -- esa composición ya no vive en `comandos/procesar.py` -- y su garantía se
      recreó en `tests/test_cli.py::test_procesar_usa_construir_engine_postgres_no_create_engine_pelado`.
- [x] 4.8 `git mv` puro -- ver 4.5 (mismo commit, ambos módulos juntos).
- [x] 4.9 GREEN (commit `270f77e`) — `comandos/servir.py`: `main()`/`_parsear_args`/
      `_tipo_procesos` reemplazados por `servir(*, db_url, puerto, raiz, procesos,
      escuchar_red)` con argumentos con nombre (misma composición interna: pepper, secreto,
      `construir_aplicacion`, servidor WSGI, apagado cooperativo). `cli.py` despacha a
      `comandos.servir.servir(...)`.
- [x] 4.10 Adaptados (commit `270f77e`):
      - `tests/comandos/test_servir.py`: `_cargar_script()` → import normal; los 14 tests que
        llamaban `modulo.main()` con `monkeypatch.setattr("sys.argv", ...)` pasan a llamar
        `modulo.servir(...)` con argumentos con nombre; retirados los 3 tests que ejercitaban
        el `argparse` propio del módulo (`test_parsear_args_expone_procesos_...`,
        `test_parsear_args_rechaza_procesos_...`, `test_el_flag_escuchar_red_es_explicito_...`)
        -- ese `argparse` ya no existe ahí, vive en `cli.py`.
      - `tests/test_cli.py`: los 4 `monkeypatch.setattr(cli, "_cargar_script", ...)` (no 5 --
        uno de los 5 originales vivía en `test_contrato_cli.py`, corregido en 4.0) pasan a
        mockear `cli.comandos_procesar.ejecutar`/`cli.comandos_servir.servir` (la función de
        comando, no el cargador); se agregan las 3 garantías movidas desde
        `tests/comandos/test_servir.py`/`test_procesar.py` (tope duro de `--procesos` para
        `procesar` y `servir`, default de `--escuchar-red`, `construir_engine_postgres` no
        `create_engine` pelado).
      - `tests/test_configuracion.py:144-164`: el centinela de `_DB_URL_DEFAULT` pasa de cargar
        los 2 scripts por ruta a importar `anonimizacion.comandos.{procesar,servir}` normal y
        confirmar identidad (`is`, no sólo `==`) contra `configuracion._DB_URL_DEFAULT` -- la
        triplicación ya es estructuralmente imposible, no sólo no observada todavía.
      - **Hallazgo no previsto en el plan** (commit `270f77e`): 3 archivos de
        `tests/caracterizacion/` (`test_codigos_cuarentena.py`, `test_pipeline_punta_a_punta.py`,
        `test_reporte_corrida.py`) también cargaban `scripts/procesar_carpeta.py` por ruta como
        fixture para llegar a `ejecutar()` real -- corrección puramente mecánica del `import`
        (mismo patrón que 4.7), CERO líneas de aserción de comportamiento tocadas (confirmado
        con `git diff`: sólo cambian el loader, imports y prosa de docstring). No estaba en el
        alcance original de 4.10 porque el plan asumía que sólo `test_contrato_cli.py` refería
        a los scripts viejos; verificado que no es así. `git diff feat/auditoria-y-poda --stat
        -- tests/caracterizacion/` por lo tanto NO queda vacío -- toca 4 archivos (los 3 de
        arriba + `test_contrato_cli.py` de 4.0) -- documentado explícitamente, no ocultado.
- [x] 4.11 Confirmado `_DB_URL_DEFAULT` en un solo lugar: `rg "^_DB_URL_DEFAULT\s*=" src/` →
      un solo resultado, `configuracion.py:49`.
- [x] 4.12 Eliminada la excepción `per-file-ignores` de `pyproject.toml` (commit `270f77e`): el
      F401 que la justificaba (import sin uso en `tests/scripts/test_servir_panel.py`) se fue
      con la mudanza; confirmado con `ruff check --select F401 tests/comandos/test_servir.py`.
- [x] 4.13 Verificación PR4: `uv run pytest -q -m "not postgres"` → 1038 passed, 1 skipped
      (symlink Windows, preexistente), 0 failed (el flake preexistente
      `test_despachar_en_paralelo_..._distintos` NO se manifestó en esta corrida -- confirmado
      aislado y dentro de `tests/trabajadores/test_despacho_paralelo.py` completo, 15/15,
      pickling real verificado empíricamente tras la mudanza). `-m postgres` → 28 passed.
      `-m empaquetado` → 3 passed (incluidos en el conteo de `not postgres`). `ruff check .` →
      All checks passed. El test de contrato del CLI de E0 (0.5) sigue pasando, con la
      corrección de 4.0 documentada como prerrequisito, no como excepción silenciosa.

## Fase 5 — Entrega 5: retiro de Celery/Redis y métricas muertas (PR5)

- [x] 5.1 Confirmado por `rg -n "\.delay\("`: único resultado en `src/`+`tests/` es
      `tests/trabajadores/test_tareas.py:143` (ahora reemplazado, ver 5.3). Todo llamador de
      producción (`comandos/procesar.py:155`, `despacho_paralelo.py:283`, y los tests de
      integración/wiring) invoca `tareas.procesar_grupo(...)` en directo.
- [x] 5.2 Eliminado `trabajadores/app.py` (y su test dedicado `tests/trabajadores/test_app.py`,
      que sólo probaba ese módulo); quitado el decorador `@app.task(name=...)` y el import de
      `app`/`aplicar_configuracion_cola` en `tareas.py`. `procesar_grupo` queda como función
      común, invocada en directo por todo llamador de producción (confirmado en 5.1).
- [x] 5.3 Reemplazado `test_procesar_grupo_via_delay_no_requiere_broker_real` por
      `test_procesar_grupo_invocado_en_directo_devuelve_el_resumen_trazable` (invocación directa,
      mismo assert sobre el resumen trazable devuelto). También corregido
      `test_procesar_grupo_recibe_exactamente_corrida_id_y_referencias`: usaba
      `tareas.procesar_grupo.run` (atributo de Celery, ya no existe sin el decorador) ->
      `inspect.signature(tareas.procesar_grupo)` directo.
- [x] 5.4 Eliminado `observabilidad/metricas.py` (`ColectorMetricas`/`MetricasEnMemoria`) y su
      test dedicado `tests/observabilidad/test_metricas.py`. En `ejecutor.py`: quitado el
      parámetro `metricas`/`self._metricas`, el método `_observar_duracion`, los 3 usos de
      escritura (`incrementar_documento_procesado`, `incrementar_fallo`, `observar_duracion_ms`
      vía `observar=` en `_ejecutar_con_reintentos`) y el parámetro `observar` de
      `_ejecutar_con_reintentos` (sin consumidor una vez retirada la métrica de duración). En
      `tareas.py`: quitado el parámetro `metricas` de `construir_fabrica_ejecutor` y la
      instancia `MetricasEnMemoria()` por grupo en `_fabrica()`. Adaptado
      `tests/pipeline/test_observabilidad_cableada.py`: retirados `_ColectorEspia`/
      `_ColectorQueExplota` y las aserciones sobre `espia_metricas`; el test de resiliencia
      (invariante 3, "la observabilidad es accesoria") se conserva pero ahora ejercita una
      `_BitacoraQueExplota` en vez de un colector de métricas roto, preservando la cobertura de
      la propiedad sin el sistema retirado.
- [x] 5.5 Eliminado `CODIGOS_SEGUROS` en `observabilidad/bitacora_segura.py:56` (sin llamador,
      confirmado por `rg -n "CODIGOS_SEGUROS"` -> sólo su propia declaración antes del borrado);
      retirado el import ahora sin uso de `CodigoErrorDocumento` en ese módulo.
- [x] 5.6 Quitado `celery>=5.3`/`redis>=5.0` de `pyproject.toml`. `uv lock` retiró las 14
      transitivas (`amqp`, `billiard`, `kombu`, `vine`, etc.) sin tocarlas a mano.
- [x] 5.7 Editado `deploy/operacion-institucional.md`: quitadas las 4 filas `CELERY_*` de la
      tabla de variables protegidas, "PostgreSQL/Redis" -> "PostgreSQL" en permisos y en la
      lista de salida a producción, y reescrita la mención de línea 5 ("el camino de
      Celery/Redis... modo de despliegue aparte") para que ya no implique que existe una
      cáscara semi-lista -- ahora dice explícitamente que se retiró en esta entrega y que el
      paralelismo real es `ProcessPoolExecutor`. También limpiado `deploy/variables-entorno.example`
      (mismas 4 variables) y actualizado `tests/deploy/test_documentacion_despliegue.py` para
      afirmar la AUSENCIA de `CELERY_` en ambos archivos en vez de su presencia.
- [x] 5.8 Verificación: `rg -n "celery|Celery" src/ pyproject.toml docker-compose.yml deploy/`
      -> sin resultados de import ni de variable `CELERY_*` (sólo prosa histórica en
      `despacho_paralelo.py`/`politica_reintentos.py` explicando por qué se descartó Celery+Redis
      como mecanismo de concurrencia, ninguna importa el paquete). `test_reporte_corrida.py`
      (E0, Requisito 5) sigue pasando **sin modificarse** (`git diff feat/auditoria-y-poda --stat
      -- tests/caracterizacion/` vacío). `MetricasDespacho` (`despacho_paralelo.py:330`) intacta:
      `tests/trabajadores/test_despacho_paralelo.py` 15/15 verde.
- [x] 5.9 `uv run pytest -q -m "not postgres"` -> 1026 passed, 1 skipped (symlink Windows,
      preexistente), 0 failed. `uv run pytest -q -m postgres` -> 28 passed. `uv run pytest -q -m
      caracterizacion` -> 17 passed. `ruff check .` -> All checks passed.
- [x] 5.10 (no en el plan original, residuo encontrado en revisión del orquestador) — retirado
      `trabajadores/politica_reintentos.py` completo (módulo huérfano de Celery: su docstring
      declaraba explícitamente el "formato que espera un `@app.task(...)` de Celery" -- el
      decorador que 5.2 ya había borrado) y su test dedicado
      `tests/trabajadores/test_politica_reintentos.py`. Confirmado por `rg -n
      "politica_reintentos" --glob '!**/politica_reintentos.py' .` -> cero importadores de
      producción, único importador el propio test. Confirmado que `BACKOFF_SEGUNDOS`/
      `MAX_REINTENTOS` (mismo nombre, trampa señalada por el orquestador) que SÍ usa producción
      viven y se importan de `pipeline/ejecutor.py:79-80`, no del módulo retirado -- ese import
      no se tocó. Limpiadas las 2 referencias por nombre que quedaban en comentarios
      (`dominio/errores.py:66`, `pipeline/ejecutor.py:77`); conservadas las de
      `despacho_paralelo.py:96,231` (documentan la decisión de arquitectura de descartar
      Celery+Redis, no un módulo inexistente). Verificación tras el borrado: `uv run pytest -q
      -m "not postgres"` -> 1024 passed, 1 skipped, 0 failed (el flake preexistente
      `test_despachar_en_paralelo_..._distintos` apareció en una corrida bajo carga y confirmó
      15/15 aislado, mismo patrón ya documentado, no es regresión); `-m postgres` -> 28 passed;
      `-m caracterizacion` -> 17 passed, `git diff feat/auditoria-y-poda --stat --
      tests/caracterizacion/` vacío; `ruff check .` -> All checks passed.

## Fase 6 — Entrega 6: migración a Obsidian + poda (PR6a–PR6f)

Migración de los 8 invariantes de la lista cerrada (spec `prosa-de-codigo` Req. 3), **TODAS
antes de cualquier poda**, en `04 - Desarrollo/pipeline de anonimizacion` (bitácora + nota de
arquitectura, formato del vault existente):

- [ ] 6.1 Migrar invariante 1/8: 875 MB RSS por `MotorPii` (ctypes) — evidencia
      `despacho_paralelo.py:79-80,217,339,752`.
- [ ] 6.2 Migrar invariante 2/8: razonamiento de concurrencia (2x núcleos; umbral de grupo
      tóxico 3→4) — `despacho_paralelo.py:68-117,160,171,179`.
- [ ] 6.3 Migrar invariante 3/8: motivo de cada `noqa: C901` — `pyproject.toml:56-72`.
- [ ] 6.4 Migrar invariante 4/8: cartel anti-espejo esquema Arrow —
      `tests/salida/test_esquema_arrow_de_exportacion.py:1-13`.
- [ ] 6.5 Migrar invariante 5/8: cartel anti-espejo codec de señal —
      `tests/salida/test_codec_senal.py`.
- [ ] 6.6 Migrar invariante 6/8: latencias medidas Postgres (54,9 ms / ~366 ms) + timeout 5s —
      `salida/destinos/postgres.py:87-135`.
- [ ] 6.7 Migrar invariante 7/8: constantes de calibración ECG (`_ANCHO_TRAZO_PT=0.43`, r=1,000,
      umbral de ruido) — `extraccion/trazos_pymupdf.py:22`, `extraccion/senal_ecg.py:10-85`.
- [ ] 6.8 Migrar invariante 8/8: trade-off del piso de confianza del DNI —
      `pii/reconocedores/dni_ar.py:43`.
- [ ] 6.9 Verificación de migración: 8 notas existen y enlazadas; listar los 8 punteros
      (`# ... -- ver D-0XX en Obsidian`) antes de tocar código. Compuerta de aceptación previa
      a abrir cualquier PR de poda.
- [ ] 6.10 GREEN — compuerta mecánica `tests/prosa/test_poda_no_toca_codigo.py` (ast antes/
      después, normalizar quitando docstrings iniciales, `ast.dump(include_attributes=False)`).
      RED de control: aplicar un cambio de prueba que altera código (ej. renombrar variable),
      confirmar rojo, revertir.
- [ ] 6.11 PR6a — grupo 1 (`dominio/`, `ingesta/` salvo `lanzador_corrida.py`,
      `configuracion.py`): docstrings ≤2 líneas; compuerta AST verde.
- [ ] 6.12 PR6b — grupo 2 (`extraccion/`, `deteccion/`, `parseo/`): recortar; insertar puntero
      del invariante 7 en `trazos_pymupdf.py:22`/`senal_ecg.py`; compuerta AST verde.
- [ ] 6.13 PR6c — grupo 3 (`reconciliacion/`, `pii/`, `pseudonimizacion/`): recortar; insertar
      puntero del invariante 8 en `dni_ar.py:43`; compuerta AST verde.
- [ ] 6.14 PR6d — grupo 4 (`salida/`, `pipeline/`): recortar; insertar puntero del invariante 6
      en `postgres.py:87-135`; compuerta AST verde.
- [ ] 6.15 PR6e — grupo 5 (`web/`, `cli.py`, `docs/pipeline.md`): recortar; corregir
      `cli.py:20-34` (quitar cita a PR #40 abierto) y `docs/pipeline.md:194` (referenciar
      `extraccion/texto_pymupdf.py`); insertar punteros de invariantes 4 y 5; compuerta AST
      verde (`docs/pipeline.md` queda fuera de la compuerta, revisión humana).
- [ ] 6.16 PR6f — grupo 6, solo y último (`despacho_paralelo.py` + `ingesta/lanzador_corrida.py`):
      insertar punteros de invariantes 1, 2 y 3; recortar; compuerta AST verde. `size:exception`
      (borrado puro de prosa ~800 líneas, respaldado por la compuerta AST).
- [ ] 6.17 Verificación final E6: los 8 invariantes tienen línea+puntero en código Y nota en
      Obsidian; ningún docstring de `src/` supera 2 líneas salvo excepción justificada; `cli.py`
      y `docs/pipeline.md` sin prosa falsa; suite verde sin cambios de comportamiento.

## Fase 7 — Higiene (fuera de la cadena)

- [ ] 7.1 Archivar `openspec/changes/correccion-orientacion-senal-ecg/` (PR #52 ya mergeado a
      `main` en `6e22d9b`) según la convención de archivado del repo. PR directo a `main`,
      independiente de `feat/auditoria-y-poda`.
