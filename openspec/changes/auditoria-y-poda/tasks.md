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

- [ ] 1.1 RED — `tests/salida/test_destinos_postgres.py`: 4to tipo simulado en whitelist sin
      escritor; hoy despacha silenciosamente a `_escribir_eco` (o similar) en vez de fallar.
- [ ] 1.2 GREEN — `postgres.py:320-391`: `_ESCRITORES_POR_TIPO` dict único (whitelist=despacho);
      `KeyError` explícito si falta el tipo.
- [ ] 1.3 RED — `tests/pipeline/test_coordinador_episodios.py`: episodio con los 3 tipos
      requeridos + un 4to tipo no requerido; hoy cae en `ESTUDIOS_FALTANTES` por `set() !=`.
- [ ] 1.4 GREEN — `CoordinadorEpisodios.__init__(tipos_requeridos)`; comparación
      `tipos_requeridos - set(tipos)` en `coordinador_episodios.py:128`; actualizar callers.
- [ ] 1.5 RED — `tests/salida/test_constructor_registro.py`: 4to tipo sin constructor
      registrado; afirma excepción explícita que nombra el tipo faltante.
- [ ] 1.6 GREEN — `constructor_registro.py:231-246`: registry dict `_CONSTRUCTORES_POR_TIPO`,
      `raise ValueError(...)` si falta (se preserva `ValueError`, no `KeyError` crudo).
- [ ] 1.7 Redactar en el PR1 el acta de una línea: "episodio con 3 tipos requeridos + 4to tipo
      deja de caer en ESTUDIOS_FALTANTES" (única divergencia semántica declarada).
- [ ] 1.8 Verificación PR1: confirmar que 1.1/1.3/1.5 fallaban en el commit previo al arreglo
      respectivo; `uv run pytest -q -m "not postgres"` y `-m postgres` verdes.

## Fase 2 — Entrega 2: vocabulario único de etapas (PR2)

- [ ] 2.1 RED — `tests/pipeline/test_vocabulario_de_etapas.py`: recorrer `src/` con `ast`,
      afirmar todo `_ETAPA` ∈ enum unificado y `EtapaDocumento ⊆ Etapa`; falla hoy (falta
      `DESPACHO` en `Etapa`, falta `COORDINACION` en `EtapaDocumento`).
- [ ] 2.2 GREEN — ampliar `pipeline/etapas.py::Etapa` a 10 miembros (+ `DESPACHO`); NO tocar
      `dominio/errores.py::EtapaDocumento` (firma y `str | EtapaDocumento` intactos).
- [ ] 2.3 RED — `tests/web/test_embudo_orden.py`: afirma la tupla `ETAPAS_EMBUDO` literal
      (reusa fixture del 0.9); falla mientras sea lista de strings independiente.
- [ ] 2.4 GREEN — `web/embudo_corrida.py`: `ORDEN_EMBUDO` explícito (orden verbatim de D4) y
      `ETAPAS_EMBUDO = tuple(e.value for e in ORDEN_EMBUDO)`.
- [ ] 2.5 RED — test de cobertura del desglose: todo miembro de `EtapaDocumento` ∈
      `ORDEN_EMBUDO` o en lista de exclusión explícita con motivo; falla si falta alguno.
- [ ] 2.6 GREEN — declarar la lista de exclusión (`DETECCION`, `DETECCION_PII`) con comentario
      de motivo en `web/embudo_corrida.py`.
- [ ] 2.7 Verificación PR2: el test 0.9/0.10 de E0 sigue pasando **sin modificarse** (E2 lo
      aprueba, no lo rompe); `ruff` limpio; suite `-m "not postgres"` verde.

## Fase 3 — Entrega 3: poder de detección en tests (PR3, split a/b si >400)

- [ ] 3.1 Agregar aserciones reales sobre el valor de retorno de `reconciliar(...)` en los 31
      tests sin oráculo de `tests/reconciliacion/` (ej. `test_ecg_mortara.py:57,77`):
      `assert == ()` en aprobados, tupla exacta esperada en degradación.
- [ ] 3.2 Demostrar manualmente (sin commitear la mutación) que 3.1 detecta una degradación
      simulada del parser; documentar en el PR.
- [ ] 3.3 RED — `tests/web/test_codigos_cuarentena_exhaustividad.py`:
      `{CodigoErrorDocumento} - {CAMPO_NO_EXTRAIDO} ⊆ EXPLICACION_POR_CODIGO.keys()`.
- [ ] 3.4 GREEN — completar entradas faltantes en `web/codigos_cuarentena.py`
      `EXPLICACION_POR_CODIGO` si 3.3 detecta huecos.
- [ ] 3.5 Renombrar `tests/pipeline/test_equivalencia_agrupacion.py` →
      `tests/pseudonimizacion/test_ventana_de_episodio.py`; eliminar comparación tautológica
      y el helper `_episodios_del_coordinador`/`_pares`.
- [ ] 3.6 Reexpresar los 3 oráculos existentes sobre `vincular_episodios` directo; agregar
      oráculos nuevos a mano (7 días exacto antes del ancla, dos anclas separadas por meses,
      episodio de un solo documento) con asserts sobre `metadata_por_episodio[...].fecha_ancla`.
- [ ] 3.7 GREEN — corregir docstring `coordinador_episodios.py:9-13`: ya no afirma que el test
      "fija esa equivalencia como contrato".
- [ ] 3.8 Verificación PR3: suite completa verde; si supera 400 líneas, partir en PR3a
      (oráculos de reconciliación) / PR3b (ventana de episodio + exhaustividad).

## Fase 4 — Entrega 4: CLI instalable por wheel (PR4a `procesar`, PR4b `servir`)

- [ ] 4.1 `tests/empaquetado/test_wheel_instalado.py`: fixture de sesión `uv build --wheel` +
      `uv venv --system-site-packages` + `uv pip install --no-deps`; test de guarda de
      honestidad (subproceso confirma `anonimizacion.__file__` y `shutil.which` dentro del venv
      efímero, ninguno en el checkout).
- [ ] 4.2 Test estático de empaquetado: el `RECORD` del wheel incluye módulos de `comandos/`
      y ningún `scripts/`.
- [ ] 4.3 RED — OBLIGATORIA: subproceso en el venv que **stubea `diagnosticar`** (hallazgos OK)
      **y `ejecutar`** (stub retorna 0), llama `anonimizacion.cli.main(["procesar", ...])`;
      afirma código 0 y stub invocado. DEBE fallar hoy: sin el stub de `diagnosticar`,
      `_reportar_diagnostico` corta en `cli.py:201` y nunca llega a `_cargar_script`
      (`cli.py:204`), dando falso verde con el defecto vivo.
- [ ] 4.4 Marcar 4.1/4.2/4.3 con `empaquetado`, incluido por defecto en `-m "not postgres"`.
- [ ] 4.5 `git mv` puro (0 líneas por `git diff -M`, commit separado): `scripts/procesar_carpeta.py`
      → `src/anonimizacion/comandos/procesar.py`; `tests/scripts/test_procesar_carpeta.py` →
      `tests/comandos/test_procesar.py`.
- [ ] 4.6 GREEN — editar `comandos/procesar.py`: quitar segundo `argparse`, monkeypatch de
      `sys.argv`; importar `_DB_URL_DEFAULT` desde `configuracion.py`; `cli.py` reemplaza
      `_cargar_script`/`spec_from_file_location` por import directo + `comandos.procesar.ejecutar(...)`
      con argumentos con nombre.
- [ ] 4.7 Adaptar `tests/comandos/test_procesar.py`: `spec_from_file_location` → import normal
      (mismo cuerpo de test, sin reescritura).
- [ ] 4.8 `git mv` puro: `scripts/servir_panel.py` → `src/anonimizacion/comandos/servir.py`;
      `tests/scripts/test_servir_panel.py` → `tests/comandos/test_servir.py`.
- [ ] 4.9 GREEN — editar `comandos/servir.py` análogo a 4.6; `cli.py` despacha a
      `comandos.servir.servir(...)`.
- [ ] 4.10 Adaptar `tests/comandos/test_servir.py`, los 5 `monkeypatch.setattr(cli, "_cargar_script", ...)`
      de `tests/test_cli.py` (mockear la función de comando, no el cargador), y
      `tests/test_configuracion.py:144-164`.
- [ ] 4.11 Confirmar `_DB_URL_DEFAULT` en un solo lugar (`configuracion.py:52`); las copias de
      `procesar_carpeta.py:80`/`servir_panel.py:107` mueren con la mudanza.
- [ ] 4.12 Eliminar la excepción `per-file-ignores` de `pyproject.toml:74-78` si el import sin
      uso se va con la mudanza.
- [ ] 4.13 Verificación PR4a/4b: `uv run pytest -q -m "not postgres"`, `-m postgres` y
      `-m empaquetado` verdes; 4.3 pasa (antes fallaba); el test de contrato del CLI de E0
      (0.5) sigue pasando **sin modificarse**.

## Fase 5 — Entrega 5: retiro de Celery/Redis y métricas muertas (PR5)

- [ ] 5.1 Confirmar por grep que ningún llamador de producción usa `.delay()`; sólo
      `tests/trabajadores/test_tareas.py:143`.
- [ ] 5.2 Eliminar `trabajadores/app.py` y el decorador `@app.task` en `tareas.py:150`; dejar
      invocación directa de `procesar_grupo`.
- [ ] 5.3 Eliminar o adaptar `tests/trabajadores/test_tareas.py:143` a invocación directa.
- [ ] 5.4 Eliminar `observabilidad/metricas.py`; eliminar sus usos en `ejecutor.py:334,610,647`
      y la instancia `MetricasEnMemoria()` de `tareas.py:135`.
- [ ] 5.5 Eliminar `CODIGOS_SEGUROS` en `observabilidad/bitacora_segura.py:56`.
- [ ] 5.6 Quitar `celery`/`redis` de `pyproject.toml:18-19`.
- [ ] 5.7 Editar `deploy/operacion-institucional.md:48-51`: quitar las 4 variables `CELERY_*`.
- [ ] 5.8 Verificación: `grep -r "import celery" src/` sin resultados; el test de reporte de
      corrida de E0 (0.11) sigue pasando **sin modificarse**; `MetricasDespacho` intacta.
- [ ] 5.9 `uv run pytest -q -m "not postgres"` y `-m postgres` verdes.

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
