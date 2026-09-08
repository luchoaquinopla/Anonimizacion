# Especificación: escritura idempotente

Capacidad consolidada a partir de `openspec/changes/archive/escritura-idempotente/` (capacidad
original) y `openspec/changes/archive/panel-de-operacion/` (Requisito 8, extiende la garantía a
cuarentena). Define qué debe ocurrir cuando el pipeline vuelve a ver un documento que ya procesó,
y qué debe ocurrir al publicar un episodio con varios documentos.

## Requisito 1: identidad estable del documento

Cada documento procesado **MUST** llevar una `clave_documento` estable, derivada del contenido
del artefacto y del pepper, hasta ambos destinos de salida.

La clave **MUST** derivarse por HMAC, con la misma convención que el resto de los identificadores
del sistema. El `sha256` crudo del contenido **MUST NOT** aparecer en ningún destino de salida.

La clave **MUST** ser estable entre corridas distintas sobre el mismo contenido, y **MUST**
cambiar si el contenido cambia.

#### Escenario: el mismo contenido produce la misma clave en dos corridas

- **Given** un documento cuyo contenido no cambió entre dos corridas
- **When** se procesa en la primera corrida y luego en una segunda corrida independiente
- **Then** la `clave_documento` calculada es idéntica en ambas

#### Escenario: contenido distinto produce clave distinta

- **Given** dos documentos con contenido diferente
- **When** se calcula la clave de cada uno con el mismo pepper
- **Then** las claves son distintas

#### Escenario: la huella cruda no llega a la salida

- **Given** un documento procesado hasta su publicación
- **When** se inspeccionan las filas escritas en la base
- **Then** ningún campo contiene el `sha256` del contenido

## Requisito 2: el contrato de la cola no cambia

El mensaje de cola **MUST** seguir transportando exactamente `{id_documento, uri, sha256}`, y el
artefacto **MUST NOT** transportar contenido ni handles.

La `clave_documento` **MUST** derivarse del lado del trabajador, a partir del `sha256` que ya
viaja, y no agregarse al mensaje.

#### Escenario: la cola conserva su forma

- **Given** el cambio aplicado
- **When** se inspecciona la firma de la tarea de cola
- **Then** sus parámetros siguen siendo exactamente `id_documento`, `uri` y `sha256`

## Requisito 3: reprocesar no duplica

Escribir un registro cuya `clave_documento` ya fue escrita **MUST NOT** crear filas nuevas, ni en
la tabla de estudios ni en ninguna tabla de mediciones.

La operación **MUST** completarse sin error: un reprocesamiento es un caso normal de operación,
no una condición excepcional.

La unicidad **MUST** anclarse en el documento. Una restricción por fila de resultado **MUST NOT**
usarse, porque los resultados de laboratorio se almacenan en formato entidad-atributo-valor y una
restricción por analito no expresa la garantía buscada.

#### Escenario: el mismo documento escrito tres veces

- **Given** un registro anonimizado con su `clave_documento`
- **When** se escribe tres veces consecutivas
- **Then** existe exactamente una fila de estudio
- **And** existe exactamente el conjunto de mediciones de una sola escritura
- **And** ninguna de las tres escrituras falla

#### Escenario: dos documentos distintos del mismo episodio

- **Given** dos documentos de tipos distintos que pertenecen al mismo episodio
- **When** se escriben ambos
- **Then** existen dos filas de estudio, una por documento

#### Escenario: la restricción resiste escritura concurrente

- **Given** dos trabajadores que escriben el mismo documento a la vez
- **When** ambos intentan insertar
- **Then** queda exactamente una fila de estudio
- **And** ninguno de los dos trabajadores termina con un error no controlado

## Requisito 4: publicar un episodio conserva todos sus documentos

Publicar un episodio con N documentos **MUST** dejar los N documentos escritos en PostgreSQL,
cada uno en su propia fila de `estudio` con la medición correspondiente.

Ningún documento del episodio **MUST** sobrescribir a otro del mismo episodio.

**Nota (2026-09-08)**: la redacción original de este requisito y del Requisito 5 (retirado, ver
abajo) hablaba de "formato analítico" y "manifiesto" — el mecanismo de publicación por archivo
(`EscritorParquet`, `PublicadorBundles`) que existía cuando se escribió esta spec. Ese mecanismo
se eliminó en `3410d6c` (`fix(salida): elimina la ruta de salida Parquet, sin llamador de
produccion`) por no tener llamador de producción; la publicación real ocurre exclusivamente vía
`src/anonimizacion/salida/destinos/postgres.py`.

#### Escenario: episodio de tres estudios

- **Given** un episodio con un electrocardiograma, un laboratorio y un ecocardiograma
- **When** se publica el episodio
- **Then** PostgreSQL contiene las tres filas de `estudio`, una por documento
- **And** los tres tipos de documento están representados

#### Escenario: republicar el mismo episodio no altera el resultado

- **Given** un episodio ya publicado
- **When** se publica nuevamente con los mismos documentos
- **Then** el contenido en PostgreSQL es idéntico al de la primera publicación (la guarda de
  `clave_documento` del Requisito 3 evita filas duplicadas)
- **And** no se agregan ni se pierden documentos

## Requisito 5 (RETIRADO 2026-09-08): republicar con un documento adicional

Redacción original: "Cuando un episodio se republica incluyendo un documento que antes faltaba,
el **manifiesto** MUST reflejar la unión de los documentos publicados, y el **formato analítico**
MUST contenerlos a todos [...] Un manifiesto desactualizado MUST NOT conservarse."

**Por qué se retira**: dependía enteramente del manifiesto de archivo de `PublicadorBundles`,
eliminado en `3410d6c` junto con `EscritorParquet` por no tener llamador de producción (ver nota
del Requisito 4). No existe manifiesto que pueda quedar desactualizado. El comportamiento
equivalente sobre la salida real (cada documento nuevo del episodio agrega su propia fila de
`estudio` vía `escribir_registro`, sin sobrescribir las anteriores) ya queda cubierto por el
Requisito 4 y por la guarda de idempotencia del Requisito 3 — no hace falta un requisito propio.

## Requisito 6: la ausencia de la clave no rompe lo ya escrito

La columna de clave de documento **MUST** aceptar ausencia, y las filas escritas antes de este
cambio **MUST** seguir siendo válidas sin ella.

No **MUST** realizarse relleno retroactivo: no hay forma de derivar la clave de una fila ya
escrita sin volver a leer el documento original.

#### Escenario: filas previas al cambio

- **Given** filas de estudio escritas antes de aplicar la migración
- **When** se aplica la migración
- **Then** esas filas conservan sus datos
- **And** su clave de documento queda ausente

## Requisito 7: contenido corregido entra como documento nuevo

Si un documento se corrige y se reprocesa, su contenido cambia, por lo tanto su clave cambia, y
**MUST** escribirse como un documento nuevo.

El sistema **MUST NOT** intentar decidir por sí mismo cuál de las dos versiones es la vigente: no
dispone de información para hacerlo.

#### Escenario: el documento se corrige en el origen

- **Given** un documento ya publicado
- **When** se corrige su contenido en el origen y se vuelve a procesar
- **Then** se escribe una fila de estudio nueva, con una clave distinta
- **And** la fila anterior se conserva

## Requisito 8: reprocesar la misma corrida no duplica el apartado

Extiende la garantía de los Requisitos 1-3 (hasta acá, sólo estudio y mediciones) a cuarentena.
Agregado por `openspec/changes/archive/panel-de-operacion/`.

Reprocesar un documento que ya fue apartado dentro de la misma corrida, con el mismo desenlace,
**MUST NOT** aumentar el conteo de documentos apartados de esa corrida.

Dos corridas distintas **MAY** registrar cada una su propio desenlace de cuarentena para el mismo
documento. Eso **MUST** contarse como historial —una fila por corrida—, no como duplicado.

La operación **MUST** completarse sin error: reprocesar es un caso normal de operación.

#### Escenario: reprocesar la misma corrida no duplica

- **Given** un documento ya apartado dentro de una corrida, con un motivo determinado
- **When** esa misma corrida se reprocesa y el documento vuelve a fallar con el mismo motivo
- **Then** el conteo de apartados de esa corrida sigue siendo el mismo que antes de reprocesar

#### Escenario: corridas distintas no se pisan

- **Given** un documento apartado en una corrida
- **When** el mismo documento se procesa como parte de una corrida distinta y también falla
- **Then** cada corrida tiene su propio registro de apartado para ese documento
- **And** el conteo de cada corrida es correcto de forma independiente

#### Escenario: el reporte de cuarentena no sobrecuenta tras reprocesar

- **Given** una corrida con un documento ya apartado
- **When** esa corrida se reprocesa por completo sobre el mismo corpus
- **Then** el reporte de cuarentena y el embudo de esa corrida siguen mostrando un único apartado
  para ese documento
