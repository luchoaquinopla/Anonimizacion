# Especificación: panel de operación

Capacidad nueva. Define el embudo de una corrida — cuántos documentos pasaron cada etapa
observable, dónde se cayeron, throughput y rango de tiempo restante — servido sin dependencias de
red y sin exponer PII. El embudo se deriva de lo que ya se persiste (ver capacidad
`trazabilidad-por-corrida`); esta especificación no agrega escrituras nuevas al camino caliente.

## Requisito 1: el embudo cierra aritméticamente

La suma de documentos publicados, apartados, con desenlace desconocido y en vuelo **MUST** ser
igual al total de documentos inventariados por la corrida.

Si esa suma no cierra, el panel **MUST** mostrarlo explícitamente en vez de repartir la
diferencia entre las demás categorías.

#### Escenario: el embudo cierra en un ensayo de volumen

- **Given** una corrida que terminó de procesar un corpus conocido
- **When** se suman publicados, apartados, desconocidos y en vuelo
- **Then** el total es igual a los documentos inventariados

#### Escenario: un descuadre se declara, no se disimula

- **Given** una corrida cuyo conteo no cierra contra el inventario
- **When** se renderiza el panel
- **Then** el panel señala el descuadre en vez de absorberlo en otra categoría

## Requisito 2: sólo se declaran las etapas realmente observables

El panel **MUST** mostrar barras únicamente para las etapas donde un documento puede caer en
cuarentena: ingesta, extracción, parseo, reconciliación, coordinación, pseudonimización y salida.

El panel **MUST NOT** dibujar barras para detección ni para detección de PII: ninguna de las dos
produce cuarentena, y una barra en cero ahí es indistinguible de una etapa no medida.

#### Escenario: siete etapas, no nueve

- **Given** el panel de una corrida en curso
- **When** se cuentan las barras del embudo
- **Then** hay exactamente siete, ninguna rotulada detección ni detección de PII

## Requisito 3: el desenlace desconocido es una categoría visible propia

El panel **MUST** mostrar "sin desenlace registrado" como columna propia del embudo, con su
propio rótulo y conteo, nunca mezclada dentro de "en vuelo" ni omitida.

#### Escenario: el residuo de infraestructura se ve

- **Given** una corrida con documentos cuyo desenlace quedó desconocido (Requisito 2 de
  `trazabilidad-por-corrida`)
- **When** se renderiza el panel
- **Then** esos documentos aparecen contados bajo "sin desenlace registrado"

## Requisito 4: el tiempo restante es un rango, nunca un número puntual

El panel **MUST** mostrar el tiempo restante como un intervalo: cota optimista, con la tasa de la
ventana móvil reciente de documentos terminados; y cota pesimista, con la tasa promedio de todo
el tiempo activo de la corrida.

El cálculo de tasa **MUST** excluir los huecos de inactividad entre pausa y reanudación.

Un documento apartado **MUST** contar como throughput, salvo el apartado por sobretamaño en
ingesta, que **MUST NOT** contar porque no llegó a leerse.

Por debajo de un mínimo de documentos terminados, el panel **MUST** mostrar un estado de
"midiendo" en vez de una estimación.

#### Escenario: el rango se muestra como intervalo

- **Given** una corrida con throughput suficiente para estimar
- **When** se renderiza el panel
- **Then** se muestran dos cotas de tiempo restante, no un único número

#### Escenario: la pausa no infla el throughput medido

- **Given** una corrida que estuvo pausada una hora y luego se reanudó
- **When** se calcula la tasa de avance
- **Then** esa hora de inactividad no se cuenta como tiempo transcurrido

#### Escenario: el sobretamaño no cuenta como trabajo hecho

- **Given** un documento apartado en ingesta por exceder el tope de tamaño
- **When** se calcula el throughput
- **Then** ese documento no se contabiliza

#### Escenario: pocos documentos terminados no producen una cifra falsa

- **Given** una corrida recién iniciada, por debajo del mínimo de documentos terminados
- **When** se renderiza el panel
- **Then** se muestra "midiendo" en vez de un rango de tiempo

## Requisito 5: una corrida sin datos tiene comportamiento definido

Una corrida recién creada, sin documentos procesados todavía, **MUST** mostrar el embudo en cero
y el estado de tiempo restante en "midiendo", sin dividir por cero ni mostrar un infinito.

#### Escenario: corrida recién creada

- **Given** una corrida creada sin ningún documento procesado
- **When** se renderiza el panel
- **Then** todas las etapas muestran cero y el tiempo restante dice "midiendo"

## Requisito 6: el panel no expone PII

El panel **MUST NOT** mostrar, encolar ni loguear ningún dato que no esté ya en las tablas que
por diseño no guardan PII.

#### Escenario: el panel no agrega nada nuevo

- **Given** las tablas de las que se deriva el embudo
- **When** se compara su contenido contra lo que muestra el panel
- **Then** el panel no expone ningún campo ausente en esas tablas

## Requisito 7: la pantalla funciona sin red

El HTML servido **MUST NOT** referenciar `http://`, `https://` ni `<script src=...>` externo. El
JavaScript de refresco periódico **MUST** ir en línea, en el mismo documento.

#### Escenario: la página no depende de recursos externos

- **Given** el panel renderizado
- **When** se inspecciona su HTML
- **Then** no aparece ninguna URL externa ni una etiqueta de script con `src`
