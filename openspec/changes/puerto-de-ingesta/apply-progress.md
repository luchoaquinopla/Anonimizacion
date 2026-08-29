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
