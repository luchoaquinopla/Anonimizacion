# Exploración: puerto de ingesta

## Estado actual

`src/anonimizacion/ingesta/fuente.py` declara en su docstring ser un puerto hexagonal, pero
no existe ningún `Protocol` ni ABC. Solo hay dos dataclasses concretas:

- `FuenteArtefacto.listar()` — directorio plano, devuelve una `list` completa.
- `InventariadorDocumentos.inventariar(directorio)` — recorrido recursivo, validación de
  raíces autorizadas, tope de tamaño y deduplicación por sha256. Recibe el directorio como
  argumento de llamada en lugar de campo del constructor, por lo que su forma es asimétrica
  respecto de `FuenteArtefacto`.

Ninguna de las dos está conectada a un despachador de producción todavía: sus únicos
consumidores son `scripts/procesar_carpeta.py` (script manual) y
`tests/fixtures/corpus_piloto.py` (generación de fixtures). El riesgo de migración es bajo,
porque nada del camino productivo depende de la forma actual.

El acoplamiento real está en `pipeline/ejecutor.py:181`: el `extraer` por defecto invoca
`extraer_texto(Path(artefacto.uri))`, y `extraer_texto` (`extraccion/texto_pymupdf.py:85`)
llama a `pymupdf.open(ruta)`. Ese es el único supuesto efectivo de filesystem local.
`ArtefactoCrudo.uri` es un `str` común, así que el acoplamiento vive en esa cadena de
llamadas, no en la dataclass.

PyMuPDF soporta de forma nativa `stream=bytes, filetype="pdf"`, de modo que un método del
puerto basado en bytes es un reemplazo directo. No hay bloqueo de librería.

El lado de salida ya tiene la forma objetivo: los `Protocol` `DestinoEscritura` y
`DestinoCuarentena` en `ejecutor.py` (líneas ~83 y ~98), con adaptadores concretos en
`salida/destinos/`. La ingesta debe reflejar esa misma simetría.

`ArtefactoCrudo` (`ingesta/artefacto.py`: `uri`, `sha256`, `formato`) cruza la cola de
Celery tal cual: el payload de `trabajadores/tareas.py` es exactamente
`{id_documento, uri, sha256}`, bajo el invariante de que la cola nunca transporta contenido
ni PII. Cualquier rediseño del puerto debe mantenerlo libre de contenido.

## Áreas afectadas

- `src/anonimizacion/ingesta/fuente.py` — donde vivirán el `Protocol` y el adaptador unificado.
- `src/anonimizacion/ingesta/artefacto.py` — contrato de `ArtefactoCrudo`; debe seguir siendo
  serializable y libre de contenido.
- `src/anonimizacion/pipeline/ejecutor.py:181` — el punto de acoplamiento real.
- `src/anonimizacion/extraccion/texto_pymupdf.py` — `extraer_texto(ruta: Path)` necesita una
  variante que acepte bytes o stream.
- `src/anonimizacion/trabajadores/tareas.py` — reconstruye `ArtefactoCrudo` desde el payload
  de la cola. Sus tareas aún no implementadas `extraer_minimo` y `extraer_completo` ya
  asumen `ArtefactoCrudo` como punto de acceso a bytes.
- `scripts/procesar_carpeta.py` — llama a `FuenteArtefacto(...).listar()` directamente.
- Tests: `tests/ingesta/test_fuente.py`, `tests/fixtures/corpus_piloto.py` (alimenta los
  ensayos de carga de `tests/carga/`), `tests/pipeline/test_ejecutor.py`,
  `tests/trabajadores/test_tareas.py`, `tests/integracion/test_salida_sin_pii.py`.

## Enfoques comparados

| Enfoque | A favor | En contra | Esfuerzo |
|---|---|---|---|
| **1. Puerto simétrico con `list` ansiosa** — `Protocol` espejado de `DestinoEscritura`; `listar() -> list[ArtefactoCrudo]` más `abrir(artefacto) -> BinaryIO`; migrar el `extraer` por defecto a `fuente.abrir(...)` | Diff mínimo; el tipo de retorno no cambia en ningún consumidor; corrige el acoplamiento real | Mantiene el hasheo ansioso de todo el corpus antes de procesar el primer archivo; no atiende el problema de streaming, que es el que importa a 5 TB | Medio |
| **2. Puerto simétrico con `Iterator` perezoso** — misma forma `listar()`/`abrir()`, pero `Iterator[ArtefactoCrudo]`, con el hasheo diferido por elemento | Es la forma correcta para una fuente futura paginada o remota; el procesamiento arranca antes de completar el inventario; atiende directamente el escenario de 5 TB en lugar del síntoma actual | Toca algunos consumidores más: los `len()` y las evaluaciones de verdad en `procesar_carpeta.py` y `test_fuente.py` deben materializar primero | Medio-alto |

Ambos enfoques requieren unificar `FuenteArtefacto` e `InventariadorDocumentos` detrás de un
único `Protocol`, conservando las validaciones de seguridad de `InventariadorDocumentos`
(raíces autorizadas, tope de tamaño, deduplicación) como línea base de cualquier adaptador.
Ambos necesitan `abrir()` dentro del mismo cambio: un puerto sin acceso a bytes no corrige
`ejecutor.py:181`.

## Recomendación

**Enfoque 2, perezoso.** El contexto de negocio habla de cientos de miles de archivos y unos
5 TB. Una lista ansiosa con hasheo completo previo es exactamente lo que habría que rehacer
apenas aparezca una fuente remota o paginada, y agregarle pereza después a un `Protocol` ya
publicado sería un cambio incompatible. El costo adicional de migración hoy es chico y
mecánico.

`abrir()` sale en el mismo cambio que `listar()`. **No** se diseña acá ningún adaptador
remoto ni de nube: el mecanismo de entrega institucional sigue sin definirse.

## Contexto de negocio

El instituto todavía no definió cómo entregará el corpus (cientos de miles de PDFs, unos
5 TB): disco local, recurso de red compartido, máquina virtual institucional o un endpoint
de API u object storage. Un invariante de privacidad rige en cualquiera de los casos: **los
PDFs crudos nunca salen del límite institucional; solo cruzan hacia nuestra base los datos
estructurados y anonimizados.** Por eso la extracción siempre corre adyacente a los bytes,
pero "adyacente" puede significar cualquiera de esos cuatro mecanismos.

El objetivo no es construir hoy un adaptador remoto. Es dejar la costura explícita y
correcta para que agregarlo mañana sea una clase nueva y no una reescritura.

## Riesgos

- Desborde de alcance hacia la publicación en nube. Este cambio se limita al puerto y a
  reubicar los adaptadores locales: sin S3, sin API, sin credenciales.
- Seguridad de la cola: `ArtefactoCrudo` debe seguir siendo serializable y libre de
  contenido, sin transportar nunca un handle ni bytes.
- La migración a iterador toca sitios de aserción (`len()`, evaluaciones de verdad), no solo
  consumidores; es fácil pasarlos por alto.
- `tests/fixtures/corpus_piloto.py` y los ensayos de `tests/carga/` dependen de la forma
  exacta de `InventariadorDocumentos.inventariar()`. Unificar exige migrarlos y volver a
  correr los benchmarks.
- Adyacente y fuera de alcance: la ventana de siete días de `coordinador_episodios.py`
  podría cambiar de rol si el instituto entrega carpetas ya agrupadas por paciente. Queda
  anotado, no se diseña acá.

## ¿Listo para propuesta?

Sí.
