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
