# Especificación: procesamiento por grupo

Capacidad nueva. Define qué es la unidad de trabajo del pipeline, cuándo un episodio se aprueba
y con qué motivo se aparta, y cómo se distingue un problema de episodio de uno de campo.

## Requisito 1: la unidad de trabajo es el grupo

El trabajador **MUST** procesar un grupo de documentos como un único lote, no un documento por
vez.

Un grupo es el conjunto de estudios que el origen entrega como pertenecientes a un mismo
paciente y episodio. El pipeline **MUST NOT** asumir que el grupo es correcto: lo valida.

El mensaje de cola **MUST** transportar únicamente referencias —identificador, ubicación y
huella de contenido por documento— y **MUST NOT** transportar contenido ni información
identificatoria.

#### Escenario: un grupo completo se procesa junto

- **Given** un grupo con un electrocardiograma, un laboratorio y un ecocardiograma del mismo paciente
- **When** el trabajador lo procesa
- **Then** los tres documentos se coordinan en un solo lote
- **And** el episodio queda aprobado

#### Escenario: el mensaje de cola no lleva contenido

- **Given** un mensaje de grupo listo para encolarse
- **When** se inspecciona su contenido
- **Then** cada entrada tiene sólo identificador, ubicación y huella
- **And** no hay bytes de documento ni datos identificatorios

## Requisito 2: la validación de episodio corre en producción

La raíz de composición de producción **MUST** inyectar el coordinador de episodios en el
ejecutor.

El ejecutor **MAY** seguir aceptando la ausencia de coordinador como modo válido: "un lote es
un episodio" es una política de despliegue, no una verdad del núcleo. Pero ningún camino de
producción **MUST** quedar sin validación de episodio.

#### Escenario: la fábrica de producción valida

- **Given** el ejecutor construido por la raíz de composición de producción
- **When** se procesa un grupo al que le falta un tipo de estudio
- **Then** sus documentos se apartan a cuarentena
- **And** ninguno se publica

#### Escenario: un grupo incompleto no publica nada

- **Given** un grupo con sólo dos de los tres tipos requeridos
- **When** el trabajador lo procesa
- **Then** no se escribe ningún registro en el destino
- **And** los dos documentos quedan apartados con el mismo motivo

## Requisito 3: los motivos de episodio son distinguibles de los de campo

Un documento apartado por un problema de **episodio** —faltan estudios, o la asociación es
ambigua— **MUST** llevar un código propio, distinto del que se usa para un problema de
**campo** —un dato que no pudo verificarse contra el documento fuente.

La distinción **MUST NOT** depender de una convención implícita, como que un campo quede vacío.

#### Escenario: falta un estudio del episodio

- **Given** un grupo al que le falta el ecocardiograma
- **When** el trabajador lo procesa
- **Then** sus documentos se apartan con un motivo de episodio incompleto
- **And** ese motivo es distinto del que se usa cuando un dato no pudo verificarse

#### Escenario: el mismo tipo de estudio aparece dos veces

- **Given** un grupo con dos laboratorios del mismo paciente y período
- **When** el trabajador lo procesa
- **Then** sus documentos se apartan con un motivo de episodio ambiguo

#### Escenario: un dato no verificable sigue teniendo su propio motivo

- **Given** un documento cuyo valor no puede citarse contra una única fuente del PDF
- **When** se reconcilia
- **Then** se aparta con un motivo de cobertura, no con uno de episodio

## Requisito 4: el total de documentos apartados no cambia

Separar los motivos **MUST** redistribuir los conteos por código sin alterar el total de
documentos apartados.

Un cambio en el total **MUST** tratarse como defecto, no como efecto esperado del cambio.

#### Escenario: el ensayo de volumen conserva su total

- **Given** el corpus sintético de mil documentos
- **When** se procesa con los motivos ya separados
- **Then** el total de documentos apartados es el mismo que antes del cambio
- **And** sólo cambia cómo se reparten entre los códigos

## Requisito 5: un documento repetido entre grupos deja incompleto al segundo

La enumeración descarta documentos cuyo contenido ya fue visto. Si un mismo contenido aparece
en dos grupos, el segundo grupo **MUST** quedar incompleto y apartarse con su motivo, en lugar
de publicarse como si estuviera completo.

Este comportamiento **MUST** quedar explícito: es consecuencia de la deduplicación por
contenido y no un caso no previsto.

#### Escenario: el mismo contenido en dos grupos

- **Given** dos grupos donde un documento de contenido idéntico aparece en ambos
- **When** se enumeran y procesan
- **Then** el primer grupo lo recibe
- **And** el segundo queda incompleto y se aparta con el motivo de episodio incompleto

## Requisito 6: el script manual valida igual que producción

La herramienta de procesamiento manual **MUST** construirse por la misma raíz de composición
que el trabajador, de modo que aplique la misma validación de episodio.

No **MUST** existir un modo de producción sin validación al que se pueda llegar por
configuración.

#### Escenario: el script manual aparta un grupo incompleto

- **Given** un directorio con un grupo al que le falta un estudio
- **When** se procesa con la herramienta manual
- **Then** ese grupo se aparta igual que lo haría el trabajador
