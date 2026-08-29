# Tareas: puerto de ingesta

## Decisión resuelta: quién asigna `corrida_id`

No es un bloqueo: el código ya lo responde. `ServicioCorridas.crear_corrida` (`web/rutas_corridas.py:23`) es solo un `Protocol` sin implementación concreta, y ningún despachador productivo llama hoy a `RepositorioCorridas.crear_corrida`. El worker (`tareas.py:41`, `configurar_ejecutor`) solo necesita `FuenteLocal.abrir()` — nunca llama `listar()` ni dedup. Por lo tanto, `HuellasDeCorrida` **sale de este cambio**. Construirla ahora dejaría una clase sin consumidor: el wiring de `tareas.py` usaría `HuellasEnMemoria()` de todos modos, con lo que pagaríamos el diseño respaldado en base sin cobrar ninguno de sus dos beneficios (sobrevivir a una interrupción y ser seguro entre workers concurrentes). Lo que sí entra es la costura: el `Protocol RegistroDeHuellas` más `HuellasEnMemoria`. `HuellasDeCorrida` se implementa junto con el despachador que la necesite, en el cambio que le dé `corrida_id`, y ahí se la puede probar de punta a punta.

## Pronóstico de carga de revisión

| Campo | Valor |
|---|---|
| Líneas estimadas | 580–720 |
| Riesgo de presupuesto 400 líneas | High |
| PRs encadenados recomendados | Yes |
| División sugerida | PR1 → PR2 → PR3 → PR4 |
| Delivery strategy | no especificada por el orquestador — se asume `ask-on-risk` |
| Chain strategy | pending — requiere elección del usuario |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Unidades de trabajo sugeridas

| Unidad | Objetivo | PR | Notas |
|---|---|---|---|
| 1 | `Protocol` de ingesta + trampa del generador + costura de dedup (Fases 1-3) | PR1 | Autónoma, tests incluidos |
| 2 | `FuenteLocal` completo: pereza, hasheo por bloques, tope, cuarentena, `abrir()` (Fases 4-5) | PR2 | Depende de PR1 |
| 3 | `extraer_texto_de_flujo` + rewiring `ejecutor.py`/`tareas.py` (Fases 6-7) | PR3 | Depende de PR2 |
| 4 | Migración de consumidores + benchmarks (Fases 8-9) | PR4 | Depende de PR3 |

Comando de test del proyecto: `pytest` (`pyproject.toml`, `testpaths = ["tests"]`). Carga: `pytest tests/carga/`.

## Fase 1: `Protocol` de ingesta

- [x] 1.1 RED: test de contrato — `FuenteLocal` debe satisfacer un `Protocol FuenteDeArtefactos` (`typing.assert_type` o chequeo estructural) en `tests/ingesta/test_fuente.py`. **Desvío documentado**: probado contra dobles mínimos definidos en el test, no contra `FuenteLocal`, porque `abrir()` no existe hasta la Fase 5 (PR2) y el `Protocol` exige ambos métodos. Ver apply-progress.md.
- [x] 1.2 GREEN: declarar `FuenteDeArtefactos` (`listar()`/`abrir()`) en `fuente.py`, espejo de `DestinoEscritura`/`DestinoCuarentena`.

## Fase 2: trampa del generador perezoso

- [x] 2.1 RED: test que llama `FuenteLocal(...).listar()` sobre ruta no autorizada SIN iterar y espera `PermissionError` inmediato.
- [x] 2.2 GREEN: `listar()` es función normal (valida raíz+directorio ansiosamente) que retorna un generador interno.

## Fase 3: deduplicación delegada

- [x] 3.1 RED: test `HuellasEnMemoria.es_nueva(sha256)` — segunda huella igual devuelve `False`.
- [x] 3.2 GREEN: `Protocol RegistroDeHuellas` + `HuellasEnMemoria` en `fuente.py`.

> `HuellasDeCorrida` (respaldo en `RepositorioCorridas`) queda deliberadamente fuera de este
> cambio: sin despachador no tendría consumidor. Ver la decisión al inicio del documento.

## Fase 4: `FuenteLocal` — pereza, hasheo, tope, cuarentena

- [x] 4.1 RED: migrar y ampliar tests de `test_fuente.py`: pereza (primer artefacto sin hashear el resto), hasheo por bloques == hash completo, symlink fuera de raíz, dedup por contenido con nombres distintos.
- [x] 4.2 RED: test sobretamaño → cuarentena con `tamano_bytes`/`tope_bytes` reales (reemplaza `pytest.raises(ValueError)` actual).
- [x] 4.3 GREEN: `dominio/errores.py` — `ARTEFACTO_SOBRETAMANO`, `EtapaDocumento.INGESTA`, campos opcionales `tamano_bytes`/`tope_bytes` en `ErrorDocumento`.
- [x] 4.4 GREEN: implementar `FuenteLocal` unificado (reemplaza `FuenteArtefacto`+`InventariadorDocumentos`) con `Protocol SumideroCuarentena` propio, sin importar `pipeline`.
- [x] 4.5 REFACTOR: eliminar `FuenteArtefacto`/`InventariadorDocumentos`, actualizar docstring de `fuente.py`. **Adelanto parcial de Fase 8**: se migraron `scripts/procesar_carpeta.py` y `tests/fixtures/corpus_piloto.py` a `FuenteLocal` para no dejar la suite en rojo — ver apply-progress.md para el detalle de qué queda para la Fase 8 formal (PR4).

## Fase 5: `abrir()` — revalidación y verificación

- [x] 5.1 RED: test `abrir()` con `uri` fuera de raíces autorizadas → `PermissionError` (simula cola envenenada).
- [x] 5.2 RED: test `abrir()` con sha256 que no coincide con el contenido real → error explícito.
- [x] 5.3 GREEN: implementar `abrir(artefacto) -> BinaryIO` en `FuenteLocal`.

## Fase 6: `extraer_texto_de_flujo`

- [ ] 6.1 RED: tests con PDF sintético en `BytesIO` — válido multipágina, corrupto (`PARSEO_INCOMPLETO`), vacío (`pymupdf.EmptyFileError` mapeado).
- [ ] 6.2 GREEN: `extraer_texto_de_flujo(flujo: BinaryIO) -> TextoExtraido` en `texto_pymupdf.py`; `extraer_texto(ruta)` pasa a envoltorio delgado.

## Fase 7: rewiring del pipeline

- [ ] 7.1 RED: test de integración — pipeline procesa un artefacto vía adaptador en memoria, sin filesystem.
- [ ] 7.2 GREEN: `ejecutor.py` — parámetro `fuente: FuenteDeArtefactos`; default `extraer` pasa a `extraer_texto_de_flujo(fuente.abrir(artefacto))`; quitar `Path`/`extraer_texto` de imports.
- [ ] 7.3 GREEN: `tareas.py:41` `configurar_ejecutor` — la fábrica construye `FuenteLocal(raices=..., tope_bytes=..., huellas=HuellasEnMemoria(), cuarentena=...)` e inyecta en `EjecutorPipeline(fuente=...)`.

## Fase 8: migración de consumidores

- [ ] 8.1 `scripts/procesar_carpeta.py` — `FuenteArtefacto(...).listar()` → `list(FuenteLocal(...).listar())`, conserva guardia `if not artefactos`.
- [ ] 8.2 `tests/fixtures/corpus_piloto.py:143` — `InventariadorDocumentos(...).inventariar(entrada)` → `tuple(FuenteLocal(raices=(directorio,), directorio=entrada, tope_bytes=10*1024*1024, huellas=HuellasEnMemoria(), cuarentena=_CuarentenaMemoria()).listar())`.
- [ ] 8.3 Test de payload de cola: confirmar `{id_documento, uri, sha256}` exacto tras el cambio (`tests/trabajadores/`).

## Fase 9: ensayos de carga y suite completa

- [ ] 9.1 Correr `pytest tests/carga/test_ejecutar_corpus.py` (1.000 PDFs) contra `ORACULO_CARGA_1000`; si el pico de memoria baja, actualizar `memoria_estimada` en `evaluar_preflight`.
- [ ] 9.2 Correr `tests/carga/ejecutar_corpus_10000.py` (10.000 PDFs); confirmar sin regresión de tiempo/memoria.
- [ ] 9.3 `pytest` completo en verde.
