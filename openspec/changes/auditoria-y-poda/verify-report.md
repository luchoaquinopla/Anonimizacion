# Verification Report

**Change**: auditoria-y-poda
**Rama**: feat/auditoria-y-poda @ 1b8ca41 (merge de PR #60)
**Mode**: Standard (no Strict TDD -- el proyecto no lo tiene activado; TDD real fue seguido y documentado ciclo por ciclo en apply-progress, verificado abajo)
**Verificacion**: final, previa a abrir PR de la integradora a main

## Completeness (tasks.md)

| Metrica | Valor |
|---|---|
| Tareas totales | 83 |
| Tareas completas | 82 |
| Tareas incompletas | 1 -- 7.1 (archivar correccion-orientacion-senal-ecg/), declarada fuera de la cadena en el propio tasks.md ("PR independiente a main, fuera de feat/auditoria-y-poda"). No bloquea esta integradora. |

## Build & Tests Execution (numeros reales, corridos en esta verificacion)

uv run pytest -q -m "not postgres":
1031 passed, 1 skipped, 28 deselected, 1 failed en 128.56s.
FAILED tests/trabajadores/test_despacho_paralelo.py::test_despachar_en_paralelo_usa_procesos_del_sistema_operativo_genuinamente_distintos

Aislado: 1 passed en 6.46s. Confirmado: es el flake preexistente documentado (sensible a carga de CPU, reproducible en main), no una regresion. El skip (symlinks en Windows) tambien es preexistente y ajeno al cambio.

uv run pytest -q -m postgres: 28 passed, 1033 deselected (57.88s). Docker puerto 5433.

uv run pytest -q -m caracterizacion: 17 passed, 1044 deselected (7.70s).

uv run pytest -q tests/empaquetado/: 3 passed (6.54s).

uv run --extra dev ruff check .: All checks passed!

Compuerta AST de prosa -- control cruzado obligatorio:
- COMPUERTA_AST_REF=main uv run pytest -q tests/prosa/: 2 failed, 6 passed. FALLA como se exigia: detecta archivos agregados/borrados/renombrados (scripts->comandos, metrics/app/politica_reintentos borrados, tests nuevos de caracterizacion/comandos/empaquetado/web) y varios modulos con AST distinto de docstrings (cambios reales de E1/E2/E4/E5). Prueba que la compuerta no pasa trivialmente cuando hay cambio de codigo.
- Sin COMPUERTA_AST_REF (usa feat/auditoria-y-poda, arbol identico a HEAD): 8 passed. Confirma que, dentro de la cadena ya integrada, la poda de E6 no toco ni un nodo de AST fuera de docstrings.

## Controles concretos adicionales

| # | Control | Resultado |
|---|---|---|
| 3 | rg -in "celery|redis" src/ pyproject.toml docker-compose.yml deploy/ | src/, pyproject.toml, docker-compose.yml: 0 coincidencias. deploy/operacion-institucional.md: 1 parrafo historico ("...un camino de Celery/Redis existio... se retiro en auditoria-y-poda E5..."), consistente con Requisito 2 (prohibe CELERY_*, no la palabra "Celery" en prosa historica). Discrepancia menor vs lo esperado: el control asumia que sobrevivirian "los dos comentarios de decision en despacho_paralelo.py" (los que E5 preservo explicitamente, tarea 5.11). Verificado con git diff main sobre ese archivo: esos dos comentarios (lineas 96 y 231 de main) fueron retirados por la poda de E6 (tarea 6.16), no comprimidos con puntero. No es regresion de comportamiento ni toca ninguno de los 8 invariantes protegidos. El razonamiento sigue vivo en docs/pipeline.md:279-287. Clasificado WARNING, no CRITICAL. |
| 4 | rg -o invariantes en src/ tests/ pyproject.toml | 9 coincidencias que cubren los 8 titulos de la spec prosa-de-codigo Requisito 3. Lista cerrada intacta. |
| 5 | rg del patron de ventana +-7 dias en src/ docs/ | 0 coincidencias. Confirmado corregido a "ancla + hasta 7 dias" en los 4 lugares. |
| 6 | git diff main sobre dominio/errores.py | La firma etapa: str | EtapaDocumento (linea 99) no cambio de tipo; el diff es exclusivamente poda de docstrings/comentarios (E6). Decision de E2 respetada. |
| 7 | Entry point instalado por wheel | tests/empaquetado/test_wheel_instalado.py -- 3 tests, los 3 pasan: guarda de honestidad, test estatico de contenido del wheel, y el test que detecta el defecto real (subproceso stubeado llega a la composicion real via cli.main con subcomando procesar, codigo 0). Coincide con D2 de design.md. |
| 8 | tareas sin marcar en tasks.md | 1 sola coincidencia: 7.1, declarada fuera de la cadena. |

Nota sobre scripts/: sigue existiendo pero solo contiene iniciar_panel.ps1/instalar.ps1 (PowerShell, nunca cargados por spec_from_file_location). Confirmado con git ls-files.

## Spec Compliance Matrix

### caracterizacion-comportamiento-actual
| Requisito | Escenario | Test | Resultado |
|---|---|---|---|
| R1 punta a punta | episodio completo fija filas conocidas | tests/caracterizacion/test_pipeline_punta_a_punta.py | COMPLIANT (17 tests del marcador caracterizacion en verde) |
| R1 punta a punta | detecta regresion real | mismo archivo, mutacion documentada en tasks.md 0.4 | COMPLIANT |
| R1 aislamiento de base | fixtures no tocan la base compartida 5433 | tests/caracterizacion/conftest.py -- CREATE/DROP DATABASE por uuid | COMPLIANT |
| R2 contrato CLI | banderas y defaults | tests/caracterizacion/test_contrato_cli.py | COMPLIANT |
| R2 contrato CLI | detecta cambio de codigo de salida | tarea 0.6, rojo documentado | COMPLIANT |
| R3 codigos de cuarentena | entrada sin evidencia -> codigo esperado | tests/caracterizacion/test_codigos_cuarentena.py | COMPLIANT |
| R3 codigos de cuarentena | detecta etapa cambiada | tarea 0.8, rojo documentado | COMPLIANT |
| R4 vista del embudo | desglose conocido | tests/caracterizacion/test_embudo.py | COMPLIANT |
| R4 vista del embudo | detecta desglose alterado | tarea 0.10, rojo documentado | COMPLIANT |
| R5 reporte de corrida | reporte con MetricasDespacho | tests/caracterizacion/test_reporte_corrida.py | COMPLIANT |
| R5 reporte de corrida | detecta lectura incorrecta | tarea 0.12, rojo documentado | COMPLIANT |
| R6 regla de honestidad | todo test debe poder fallar | las 5 evidencias de rojo, documentadas | COMPLIANT |

### extensibilidad-tipo-documento
| Requisito | Escenario | Test | Resultado |
|---|---|---|---|
| R1 despacho Postgres por dict | 4to tipo sin entrada falla ruidosamente | tests/salida/destinos/test_postgres.py -- _escritores_por_tipo | COMPLIANT, RED confirmado en cafaf51 |
| R1 despacho Postgres por dict | 4to tipo con entrada despacha correctamente | mismo archivo | COMPLIANT |
| R2 tipos requeridos inyectados | episodio completo + 4to tipo no cae en ESTUDIOS_FALTANTES | tests/pipeline/test_coordinador_episodios.py | COMPLIANT, RED confirmado en a1ffed5 |
| R2 tipos requeridos inyectados | episodio incompleto sigue detectandose | mismo archivo | COMPLIANT |
| R3 registry constructor | 4to tipo sin constructor falla explicito | tests/salida/test_constructor_registro.py -- _CONSTRUCTORES_POR_TIPO | COMPLIANT, RED confirmado en ba3db52 |
| R3 registry constructor | 4to tipo con constructor construye registro | mismo archivo | COMPLIANT |
| R4 rojo-verde sobre 4to tipo | cada arreglo demuestra rojo con 4to tipo | 1.1/1.3/1.5, evidencia por commit | COMPLIANT |
| Extension no listada en spec, hallazgo adversarial | salida/exportacion.py mismo patron de else mudo | tests/salida/test_exportacion.py -- _PROCESADORES_POR_TIPO, RED en 78f29dc | Corregido, documentado como extension legitima |

### vocabulario-etapas-pipeline
| Requisito | Escenario | Test | Resultado |
|---|---|---|---|
| R1 enum unificado | 3 fuentes son miembros | pipeline/etapas.py Etapa (10 miembros) | COMPLIANT |
| R2 ErrorDocumento.etapa sigue str | string plano valido | confirmado por diff + tests preexistentes | COMPLIANT |
| R3 test de deriva _ETAPA vs enum | agregar etapa de un solo lado falla | tests/pipeline/test_vocabulario_de_etapas.py | COMPLIANT, RED confirmado en 9a349ea |
| R4 ETAPAS_EMBUDO derivado con orden explicito | reordenar enum no reordena embudo | web/embudo_corrida.py ORDEN_EMBUDO + tests/web/test_embudo_orden.py | COMPLIANT, RED confirmado en 049ad58 |
| R4 no rompe la vista del embudo | mismo fixture de E0 | tests/caracterizacion/test_embudo.py sin modificar, verde | COMPLIANT |

### poder-deteccion-tests
| Requisito | Escenario | Test | Resultado |
|---|---|---|---|
| R1 reconciliar sobre retorno | degradacion silenciosa detectada | 31 tests de tests/reconciliacion/, demostrado con mutacion real (tarea 3.2) | COMPLIANT |
| R1 | extraccion completa sigue aprobando | mismos archivos | COMPLIANT |
| R2 exhaustividad de codigos | codigo nuevo sin explicacion falla | tests/web/test_codigos_cuarentena_exhaustividad.py | COMPLIANT, RED confirmado en fd003d7 |
| R2 | todos los codigos actuales tienen explicacion | mismo archivo, verde hoy | COMPLIANT |
| R3 espejo tautologico resuelto | test reemplazado detecta regresion de agrupacion | tests/pseudonimizacion/test_ventana_de_episodio.py -- 6 tests, oraculos escritos a mano | COMPLIANT, RED confirmado por mutacion de _VENTANA_DIAS |
| R3 | docstring corregido | coordinador_episodios.py lineas 9-13 | COMPLIANT |

### punto-entrada-instalable
| Requisito | Escenario | Test | Resultado |
|---|---|---|---|
| R1 CLI sin scripts/ fuera del paquete | no se cargan por ruta | cli.py -- importa comandos.procesar/comandos.servir normal | COMPLIANT |
| R2 comando funciona instalado por wheel | --help funciona | test_wheel_instalado_ejecuta_dentro_del_venv_no_del_checkout | COMPLIANT |
| R2 | subcomando real funciona | test_procesar_instalado_por_wheel_llega_a_la_composicion_real | COMPLIANT, unico test que detecta el defecto original, RED confirmado contra ad9521c |
| R2 | detecta reintroduccion de scripts/ | mismo test, por diseno | COMPLIANT |
| R3 _DB_URL_DEFAULT unico | un cambio afecta todos los usos | 1 sola coincidencia en configuracion.py linea 18 | COMPLIANT |

### retiro-celery-y-metricas-muertas
| Requisito | Escenario | Test | Resultado |
|---|---|---|---|
| R1 sin Celery en src/ | busqueda de import celery | 0 coincidencias | COMPLIANT |
| R1 | procesar_grupo invocado directo sigue funcionando | test_procesar_grupo_invocado_en_directo_devuelve_el_resumen_trazable | COMPLIANT |
| R2 doc sin CELERY_ | busqueda de CELERY_ | test_documentacion_despliegue.py afirma ausencia | COMPLIANT |
| R3 metricas muertas retiradas | metricas.py ausente, CODIGOS_SEGUROS ausente | confirmado por lectura directa | COMPLIANT |
| R4 MetricasDespacho intacta | reporte sigue leyendo | test_reporte_corrida.py sin modificar, verde; test_despacho_paralelo.py verde | COMPLIANT |

### prosa-de-codigo
| Requisito | Escenario | Test/evidencia | Resultado |
|---|---|---|---|
| R1 migrar antes de podar | ningun borrado sin nota previa | Tareas 6.1-6.9, borradores verificados antes de cada poda | PARTIAL, la escritura real en Obsidian (6.9) ocurre fuera del repo, no verificable mecanicamente desde este contexto; se confia en la declaracion explicita del apply-progress |
| R2 docstrings de maximo 2 lineas | docstring largo se recorta | lectura directa de modulos podados, excepciones documentadas en 6.12/6.17 | COMPLIANT |
| R3 lista cerrada de invariantes | invariante presente tras la poda | 9 coincidencias, 8 titulos unicos | COMPLIANT |
| R3 | PR rechazado por perder invariante | N/A, no se perdio ninguno | COMPLIANT |
| R4 prosa desincronizada corregida | cli.py sin la referencia al PR 40 abierto | sin coincidencias | COMPLIANT |
| R4 | docs/pipeline.md referencia modulo real | sin coincidencias de la ruta vieja; referencia real confirmada | COMPLIANT |
| R5 volumen informativo, no compuerta | prosa no decide la entrega | medido: 918 lineas docstring + 368 comentario = 1286 lineas en src/, por debajo del objetivo informativo de ~1500 | COMPLIANT |

Resumen de compliance: 44/45 escenarios COMPLIANT con test que pasa y puede fallar. 1 PARTIAL (R1 de prosa-de-codigo, migracion a Obsidian, fuera del alcance verificable de este repo).

## Assertion Quality Audit

Revisados los archivos de test nuevos/modificados de mayor riesgo (test_postgres.py, test_coordinador_episodios.py, test_constructor_registro.py, test_exportacion.py, test_vocabulario_de_etapas.py, test_embudo_orden.py, test_codigos_cuarentena_exhaustividad.py, test_ventana_de_episodio.py, test_wheel_instalado.py, los 31 tests de tests/reconciliacion/):

- Sin tautologias.
- Sin loops fantasma sobre colecciones potencialmente vacias.
- Sin asserts huerfanos que no llaman codigo de produccion.
- test_ventana_de_episodio.py reemplaza explicitamente un patron f(x) igual g(x) con f delegando en g por oraculos escritos a mano con fechas y agrupaciones esperadas -- exactamente el patron correcto exigido por la spec.
- Los 31 tests de tests/reconciliacion/ fueron auditados por tarea; "assert resultado is not None" tiene 0 coincidencias.

Assertion quality: sin hallazgos CRITICAL ni WARNING en los archivos de mayor riesgo revisados.

## Coherence (Design)

| Decision de design.md | Seguida | Notas |
|---|---|---|
| D1 -- E0 caracteriza solo el universo alcanzable hoy | Si | tests/caracterizacion/ no usa ningun tipo simulado |
| D1 -- aislamiento de base con CREATE/DROP DATABASE por fixture | Si | Confirmado en conftest.py |
| D2 -- wheel test que llega a la composicion, no solo --help | Si | El test de composicion real es el que detecta el defecto |
| D3 -- paquete comandos/, cli.py conserva argparse unico | Si | comandos/procesar.py, comandos/servir.py existen |
| D4 -- orden del embudo preservado verbatim, deteccion/deteccion_pii excluidas | Si | ORDEN_EMBUDO con 8 miembros en el orden documentado |
| D5 -- test tautologico reemplazado, no eliminado | Si | test_ventana_de_episodio.py conserva y amplia los 3 oraculos originales |
| D6 -- compuerta AST mecanica, comentarios fuera del AST | Si | Confirmado con la corrida cruzada (main falla, feat pasa) |
| D7 -- presupuesto de PR con size:exception en PR0/PR4/PR6f | Si, segun tasks.md | No re-medido el tamano real de cada PR ya mergeado desde este contexto de solo lectura |

## Issues Found

CRITICAL: Ninguno.

WARNING:
1. Perdida de contexto no critica en despacho_paralelo.py: los dos comentarios de decision "por que se descarto Celery+Redis" (lineas 96 y 231 de main), que la Entrega 5 (tarea 5.11) documento como preservados deliberadamente, fueron retirados sin puntero durante la poda de E6 (tarea 6.16). No es una regresion de comportamiento, no toca ninguno de los 8 invariantes de la lista cerrada de prosa-de-codigo Requisito 3, y el razonamiento sigue documentado en docs/pipeline.md lineas 279-287. Se marca WARNING porque el control de verificacion solicitado explicitamente esperaba que sobrevivieran, y es la clase de perdida silenciosa que la ronda de restauracion adversarial (apply-progress, obs 1348) busco activamente pero no cubrio este caso puntual.
2. Migracion a Obsidian (R1 de prosa-de-codigo) no verificable mecanicamente desde este contexto: tasks.md marca 6.9 como completada por el orquestador con aprobacion humana el 16/09/2026, pero no hay forma de confirmar desde el repositorio que las 8 notas existen y estan enlazadas en el vault.

SUGGESTION:
1. Considerar, en un PR de higiene posterior (o dentro de la tarea 7.1), agregar de vuelta una linea de puntero breve en despacho_paralelo.py senalando donde vive ahora la justificacion de "por que no Celery/Redis", coherente con el patron que E6 ya usa para los 8 invariantes protegidos.
2. La tarea 7.1 (archivar correccion-orientacion-senal-ecg/) queda pendiente, correctamente fuera de esta cadena -- no bloquea el merge de la integradora, pero conviene no perderla de vista.

## Verdict

PASS WITH WARNINGS -- listo para abrir el PR de feat/auditoria-y-poda a main.

Las 7 entregas (E0-E6) estan implementadas, cada requisito de las 7 specs tiene un test real que puede fallar y fallo en algun punto de la cadena (evidencia de rojo documentada), la suite completa esta verde salvo el flake preexistente y documentado, el linter esta limpio, la compuerta de prosa demuestra mecanicamente que la poda no toco codigo, y los 8 invariantes protegidos sobreviven con puntero verificable en el codigo. Los dos WARNING encontrados (perdida de un comentario de decision no critico, y la imposibilidad de verificar mecanicamente el vault de Obsidian desde este contexto) no bloquean el merge: ninguno compromete un requisito MUST de las specs ni reintroduce un defecto de los que esta cadena existe para cerrar.

---

## Resolución de las advertencias (orquestador, 16/09/2026)

**W1 — Comentarios de la decisión "procesos y no cola" perdidos en la poda.** Restaurada una línea al inicio de `trabajadores/despacho_paralelo.py`, con puntero a `docs/pipeline.md` ("Concurrencia"). La razón de no pasar el pepper como argumento ya estaba conservada en `inicializar_trabajador`.

**W2 — Migración a Obsidian no verificable desde el repositorio.** Verificada por el orquestador con acceso al vault: la nota `04 - Desarrollo/pipeline de anonimizacion/Invariantes medidos — Pipeline de anonimización.md` existe, su mapa de encabezados tiene exactamente las 8 secciones cuyos títulos citan los punteros del código, y está enlazada desde la nota de arquitectura (sección "Referencias") y desde la Guía de documentación (tabla "Dónde está cada cosa"). Se escribió **antes** de la poda (#60), como exige el Requisito 1.
