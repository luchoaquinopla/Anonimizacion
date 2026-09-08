# Especificación: trazabilidad por corrida

Capacidad nueva. Define que toda fila producida durante una corrida es atribuible a ella y
datable, y que el desenlace de cada documento que la corrida inventarió es siempre uno de tres:
publicado, apartado, o explícitamente desconocido. Ninguna de las tres puede quedar implícita.

## Requisito 1: la corrida se atribuye al grano de documento, no al de episodio

`estudio` y `cuarentena` son grano de documento: una fila por documento que la corrida procesó.
Cada fila **MUST** llevar el identificador de la corrida que la produjo.

`episodio` **MUST NOT** llevar identificador de corrida. Un episodio es una entidad clínica que
trasciende la corrida que lo originó: `escribir_episodio` es insert-si-no-existe, y un episodio
puede completarse a lo largo de dos o más corridas —una lo crea con los estudios que tiene, otra
posterior le agrega el que faltaba—. Estampar la corrida de creación afirmaría que esa corrida
sola lo produjo, y eso sería falso desde la segunda corrida en adelante. Esto es una decisión
deliberada, no una omisión: no se corrige agregando la columna más adelante.

Las tablas de medición **MUST NOT** llevar identificador de corrida tampoco, pero por un motivo
distinto: cuelgan de `estudio.id_estudio`, así que su atribución se obtiene por join contra
`estudio` sin duplicar el dato. En `episodio` la columna sería incorrecta; en mediciones sería
redundante. No son el mismo caso y no **MUST** tratarse como si lo fueran.

La tabla de estudios **MUST** además registrar su propio momento de creación, distinto de la
fecha del episodio, porque sin él no hay forma de calcular una tasa de avance.

#### Escenario: las filas de documento quedan atribuidas a su corrida

- **Given** un grupo procesado bajo una corrida determinada
- **When** se escriben sus filas de estudio
- **Then** todas llevan el identificador de esa corrida

#### Escenario: la cuarentena también queda atribuida

- **Given** un documento de una corrida que falla y se aparta
- **When** se inspecciona la fila de cuarentena resultante
- **Then** lleva el identificador de esa misma corrida

#### Escenario: un episodio completado en dos corridas no queda atribuido a una sola

- **Given** un episodio creado por una corrida con dos de sus estudios, y completado semanas
  después por otra corrida que agrega el estudio que faltaba
- **When** se consulta la atribución de sus filas
- **Then** cada estudio queda atribuido a la corrida que lo escribió
- **And** la fila de episodio no queda atribuida en exclusiva a ninguna de las dos corridas

#### Escenario: cada fila de estudio tiene su propio momento

- **Given** varias filas de estudio escritas en momentos distintos de una misma corrida
- **When** se consulta el momento de creación de cada una
- **Then** cada fila tiene el suyo, y no comparte el de la fecha ancla del episodio

## Requisito 2: el desenlace de un documento inventariado nunca queda implícito

Una vez que la corrida alcanza un estado terminal, cada documento que inventarió **MUST** tener
un desenlace determinable: publicado (tiene fila en estudio), apartado (tiene fila en
cuarentena), o desconocido (ninguna de las dos, pese a haber sido tomado por el ejecutor).

El sistema **MUST NOT** dejar un documento sin desenlace determinable indefinidamente después de
terminada la corrida: la ausencia de fila en ambos destinos es en sí misma información y
**MUST** poder distinguirse de un documento que la corrida todavía no llegó a procesar.

#### Escenario: una corrida terminada no deja residuo sin explicar

- **Given** una corrida que alcanzó un estado terminal
- **When** se cuentan los documentos inventariados que no tienen fila en estudio ni en cuarentena
- **Then** ese residuo se reporta como desenlace desconocido, no como trabajo pendiente

#### Escenario: el fallo al escribir la cuarentena no hace desaparecer al documento

- **Given** un documento cuya escritura a cuarentena falla por un problema de infraestructura,
  aunque el ejecutor ya lo dio por terminado
- **When** la corrida a la que pertenece alcanza un estado terminal
- **Then** ese documento se cuenta como desenlace desconocido, no como publicado ni como apartado
