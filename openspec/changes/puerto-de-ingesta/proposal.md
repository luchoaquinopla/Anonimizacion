# Propuesta: puerto de ingesta

## Intención

`ingesta/fuente.py` dice ser un puerto hexagonal pero no declara ningún `Protocol`: hay dos dataclasses concretas y asimétricas (`FuenteArtefacto.listar()` e `InventariadorDocumentos.inventariar(directorio)`). El acoplamiento real vive en `pipeline/ejecutor.py:181`, donde el `extraer` por defecto hace `extraer_texto(Path(artefacto.uri))` y termina en `pymupdf.open(ruta)`: filesystem local cableado en el core.

El instituto todavía no definió cómo entregará el corpus (cientos de miles de PDFs, ~5 TB): disco, recurso de red, VM institucional o endpoint remoto. No construimos hoy ese adaptador; dejamos la costura explícita para que mañana sea una clase nueva y no una reescritura.

## Alcance

### Dentro de alcance
- `Protocol` de ingesta que espeje la simetría de `DestinoEscritura`/`DestinoCuarentena` (`ejecutor.py` ~L83/L98).
- `listar() -> Iterator[ArtefactoCrudo]` perezoso, con sha256 diferido por elemento.
- `abrir(artefacto) -> BinaryIO` en el MISMO cambio: sin acceso a bytes el puerto no corrige `ejecutor.py:181`.
- Unificar `FuenteArtefacto` e `InventariadorDocumentos` en un único adaptador local, conservando raíces autorizadas, tope de tamaño y deduplicación como línea base.
- Rewiring de `ejecutor.py:181` y variante de `extraer_texto` que acepte bytes/stream (`pymupdf.open(stream=..., filetype="pdf")`).
- Migrar consumidores y aserciones: `scripts/procesar_carpeta.py`, `tests/ingesta/test_fuente.py`, `tests/fixtures/corpus_piloto.py`.

### Fuera de alcance
- Adaptadores remotos, nube, S3, API o credenciales.
- Publicación incremental hacia la base cloud.
- Rediseño de `coordinador_episodios.py` y su ventana de siete días.
- Implementar `extraer_minimo` / `extraer_completo` en `trabajadores/tareas.py`.

## Invariantes

1. **Privacidad:** los PDFs crudos nunca salen del límite institucional; solo cruzan datos estructurados y anonimizados.
2. **Cola limpia:** `ArtefactoCrudo` sigue serializable y libre de contenido. Payload de Celery: `{id_documento, uri, sha256}`.
3. **Sin regresión de seguridad:** raíces autorizadas y tope de tamaño no se pierden en la unificación.

## Capacidades

### Capacidades nuevas
- `ingesta-de-artefactos`: puerto de ingesta perezoso (`listar`/`abrir`) y adaptador de filesystem local con validaciones de seguridad.

### Capacidades modificadas
- Ninguna. `openspec/specs/` está vacío (no hay specs consolidadas todavía).

## Enfoque

Enfoque 2 de la exploración, ya decidido: puerto simétrico con `Iterator` perezoso. Se prefiere sobre la lista ansiosa porque el hasheo completo previo del corpus habría que rehacerlo apenas aparezca una fuente paginada o remota, y agregar pereza a un `Protocol` ya publicado sería incompatible. `FuenteArtefacto.listar()` hoy hace `read_bytes()` entero en memoria; el adaptador unificado hereda el hasheo por bloques del `InventariadorDocumentos`.

## Áreas afectadas

| Área | Impacto | Descripción |
|---|---|---|
| `src/anonimizacion/ingesta/fuente.py` | Modificado | `Protocol` + adaptador local unificado |
| `src/anonimizacion/ingesta/artefacto.py` | Sin cambios | Se verifica que siga libre de contenido |
| `src/anonimizacion/pipeline/ejecutor.py` | Modificado | L181 pasa a usar `fuente.abrir(...)` |
| `src/anonimizacion/extraccion/texto_pymupdf.py` | Modificado | Variante por bytes/stream |
| `scripts/procesar_carpeta.py` | Modificado | Materializar el iterador |
| `tests/ingesta/`, `tests/fixtures/corpus_piloto.py`, `tests/pipeline/`, `tests/trabajadores/` | Modificado | Migración de forma y aserciones |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| Se pierde una validación de seguridad al unificar | Media | Tests dedicados de raíz no autorizada y tope de tamaño antes del rewiring |
| Aserciones con `len()` o verdad sobre el iterador quedan sin migrar | Alta | Barrido explícito de consumidores; `pytest` completo |
| `corpus_piloto.py` y `tests/carga/` dependen de `inventariar()` | Alta | Migrar el fixture y correr los benchmarks de nuevo (1000 y 10000 PDFs) |
| Desborde de alcance hacia la nube | Media | Fuera de alcance declarado arriba |
| `ArtefactoCrudo` termina cargando bytes o un handle | Baja | Test de serialización del payload de cola |

## Plan de rollback

`git revert` del rango de commits del cambio. Es barato y suficiente porque: (a) es un contrato **interno**, sin API pública ni consumidores productivos —los únicos llamadores actuales son un script manual y fixtures de test—; (b) no hay migración de datos, esquema ni estado persistido; (c) los adaptadores locales conservan el mismo comportamiento observable, así que revertir devuelve el sistema a un estado idéntico. Si el fallo aparece parcial, el rewiring de `ejecutor.py:181` se puede revertir solo, dejando el puerto nuevo sin consumidores.

## Dependencias

- PyMuPDF ya soporta `stream=`/`filetype=`. Sin dependencias nuevas.

## Criterio de éxito

- [ ] Existe un `Protocol` de ingesta con `listar() -> Iterator[ArtefactoCrudo]` y `abrir(artefacto) -> BinaryIO`; el adaptador local lo satisface (verificable con `typing.assert_type` o un chequeo estático).
- [ ] `pipeline/ejecutor.py` no contiene ninguna referencia a `Path(artefacto.uri)` ni a `pathlib` para leer artefactos.
- [ ] Un test demuestra que el pipeline procesa un artefacto cuyos bytes provienen de un adaptador en memoria, sin filesystem.
- [ ] Un test demuestra que `listar()` emite el primer `ArtefactoCrudo` sin haber hasheado el resto del directorio.
- [ ] Se conservan tests que fallan ante raíz no autorizada, archivo sobre el tope de tamaño y duplicado por sha256.
- [ ] El payload de cola sigue siendo exactamente `{id_documento, uri, sha256}`.
- [ ] `pytest` en verde y benchmarks de `tests/carga/` (1000 y 10000 PDFs) corridos de nuevo sin regresión de tiempo.
