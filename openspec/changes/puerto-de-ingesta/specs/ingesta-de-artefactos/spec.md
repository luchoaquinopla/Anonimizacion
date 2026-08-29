# Especificación: ingesta-de-artefactos

## Propósito

Define el puerto de ingesta que el pipeline usa para descubrir y leer artefactos crudos (hoy PDFs locales) sin acoplarse a un mecanismo de entrega concreto. El puerto MUST ser simétrico con `DestinoEscritura`/`DestinoCuarentena` (`pipeline/ejecutor.py`) y MUST sostener corpus de cientos de miles de archivos (~5 TB) sin agotar memoria ni bloquear el inicio del procesamiento hasta terminar de inventariar todo el directorio.

## Requisitos

### Requirement: Puerto de ingesta simétrico y perezoso

El sistema MUST exponer un `Protocol` de ingesta con dos operaciones: `listar() -> Iterator[ArtefactoCrudo]` y `abrir(artefacto: ArtefactoCrudo) -> BinaryIO`. Ningún consumidor del pipeline MUST leer bytes de artefactos por otra vía (p. ej. `Path(artefacto.uri)` directo).

#### Scenario: Un archivo válido se lista y se abre a través del puerto

- GIVEN un directorio autorizado con un único PDF válido bajo el tope de tamaño
- WHEN se invoca `listar()` sobre ese directorio y luego `abrir()` con el `ArtefactoCrudo` obtenido
- THEN `listar()` produce exactamente un `ArtefactoCrudo` con `formato=PDF` y `sha256` del contenido real
- AND `abrir()` retorna un flujo de bytes legible con ese mismo contenido, sin exponer una ruta de filesystem al llamador

#### Scenario: `listar()` emite artefactos antes de terminar de recorrer el directorio

- GIVEN un directorio autorizado con múltiples PDFs válidos
- WHEN se consume el iterador de `listar()` tomando solo el primer elemento
- THEN el primer `ArtefactoCrudo` se obtiene sin que el resto de los archivos del directorio hayan sido leídos ni hasheados

#### Scenario: Directorio de ingesta vacío no produce artefactos

- GIVEN un directorio autorizado sin archivos soportados
- WHEN se invoca `listar()`
- THEN el iterador se agota sin producir ningún `ArtefactoCrudo` y sin lanzar error

#### Scenario: Directorio de ingesta inexistente falla explícito

- GIVEN una ruta que no existe como directorio
- WHEN se invoca `listar()` sobre esa ruta
- THEN el sistema lanza `FileNotFoundError` antes o al iniciar la iteración, de forma explícita

### Requirement: Raíces autorizadas como falla dura

El sistema MUST validar que toda ruta listada resuelva dentro de al menos una raíz autorizada configurada. Una ruta fuera de raíz autorizada MUST tratarse como error irrecuperable de la operación de ingesta, NO como cuarentena: a diferencia del sobretamaño, esto detiene la iteración porque indica una configuración de seguridad incorrecta, no un documento individual defectuoso.

#### Scenario: Ruta fuera de raíz autorizada lanza error duro

- GIVEN un puerto configurado con una única raíz autorizada
- WHEN se invoca `listar()` (o el método equivalente que recibe el directorio) sobre una ruta fuera de esa raíz
- THEN el sistema lanza `PermissionError` y NO produce ningún `ArtefactoCrudo`

### Requirement: Cuarentena de artefactos sobredimensionados

Cuando un archivo individual supera el tope de tamaño configurado, el sistema MUST apartarlo a cuarentena con un motivo que incluya el tamaño real del archivo y el tope aplicado, y MUST continuar la iteración con el resto del directorio. El sistema MUST NOT abortar el lote completo por un único archivo sobredimensionado.

#### Scenario: Archivo sobredimensionado va a cuarentena sin frenar el lote

- GIVEN un directorio autorizado con un PDF que supera el tope de tamaño configurado y otro PDF válido bajo el tope
- WHEN se consume `listar()` por completo
- THEN el archivo sobredimensionado se reporta en cuarentena con un motivo que expresa su tamaño real en bytes y el tope aplicado en bytes
- AND el `ArtefactoCrudo` del PDF válido restante se produce igual, sin que la iteración se interrumpa

### Requirement: Tope de tamaño como configuración explícita

El tope de tamaño máximo por archivo MUST ser un parámetro de configuración del adaptador, no un valor fijo en el código. En ausencia de configuración explícita, el sistema SHOULD aplicar un valor provisional de 50 MiB, documentado como sujeto a ajuste cuando se mida el corpus real del instituto.

#### Scenario: El tope configurado determina el umbral de cuarentena

- GIVEN un adaptador configurado con un tope de tamaño de N bytes
- WHEN se lista un archivo de exactamente N+1 bytes
- THEN ese archivo se aparta a cuarentena por sobretamaño
- AND un archivo de exactamente N bytes se procesa como válido

### Requirement: Deduplicación por contenido

El sistema MUST evitar producir más de un `ArtefactoCrudo` para archivos con el mismo contenido (mismo sha256) dentro de una misma operación de listado, sin importar cuántas rutas distintas contengan ese contenido.

#### Scenario: Dos archivos con el mismo contenido producen un único artefacto

- GIVEN un directorio autorizado con dos PDFs de nombres distintos pero contenido binario idéntico
- WHEN se consume `listar()` por completo
- THEN el sistema produce exactamente un `ArtefactoCrudo` para ese contenido

### Requirement: Cálculo de huella sin cargar el archivo completo en memoria

El cálculo de sha256 de cada artefacto MUST procesar el archivo en bloques, sin requerir que el contenido completo resida en memoria a la vez. Esto es obligatorio para sostener archivos que pueden ser significativamente más grandes que la memoria disponible del proceso a la escala del corpus institucional (~5 TB).

#### Scenario: El sha256 calculado por bloques coincide con el hash del contenido completo

- GIVEN un PDF válido de tamaño arbitrario dentro del tope configurado
- WHEN se calcula su huella a través del puerto
- THEN el `sha256` resultante es idéntico al que produce hashear el contenido completo de una sola vez

### Requirement: Artefacto crudo libre de contenido

`ArtefactoCrudo` MUST seguir siendo serializable sin transportar bytes ni handles de archivo abiertos. El payload que cruza la cola de tareas asíncronas MUST seguir siendo exactamente `{id_documento, uri, sha256}`, preservando el invariante de que ningún PDF crudo cruza el límite institucional a través de la cola.

#### Scenario: El payload de cola no incluye contenido del documento

- GIVEN un `ArtefactoCrudo` producido por el puerto de ingesta
- WHEN se construye el mensaje de cola para ese documento
- THEN el mensaje contiene únicamente `id_documento`, `uri` y `sha256`, sin bytes del PDF ni referencias a un descriptor de archivo abierto
