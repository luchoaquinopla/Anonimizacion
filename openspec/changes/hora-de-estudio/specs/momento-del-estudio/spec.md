# Especificación: momento-del-estudio

## Propósito

Define el comportamiento del pipeline para capturar, normalizar, dar procedencia y propagar la
**hora del estudio** como dato de primera clase, separado de `fecha_estudio: date`. La hora es
insumo directo de una variable de investigación (delta temporal ECG↔laboratorio) y por eso MUST
distinguir, sin ambigüedad, tres estados: hora presente y válida, ausencia porque el documento no
la trae, y ausencia porque el documento la trae pero no pudo leerse. Esta especificación describe
comportamiento observable, no el esquema de persistencia (columna SQL, tabla, migración), que es
decisión de diseño.

## Requisitos

### Requirement: Campo de hora opcional, separado de la fecha

El sistema MUST exponer la hora del estudio como un campo **opcional** distinto de
`fecha_estudio: date`, tanto en `DocumentoParseado` como en `RegistroAnonimizado`. El sistema
MUST NOT migrar `fecha_estudio` a `datetime` ni fusionar fecha y hora en un único valor.

#### Scenario: Fecha y hora viajan como campos independientes

- GIVEN un documento parseado con fecha y hora ambas disponibles
- WHEN se construye el `DocumentoParseado`
- THEN `fecha_estudio` conserva el tipo `date`
- AND la hora está disponible en un campo separado, sin alterar `fecha_estudio`

### Requirement: Ausencia explícita cuando el documento no trae hora

Cuando el tipo de documento no incluye hora en su layout (ecocardiograma), el sistema MUST emitir
ausencia explícita (`None` o equivalente) en el campo de hora. El sistema MUST NOT sustituir la
ausencia por un valor por defecto (p. ej. medianoche) en ninguna etapa, incluida la salida final.

#### Scenario: Ecocardiograma sin hora emite ausencia, nunca un default

- GIVEN un ecocardiograma cuyo documento fuente no trae ningún campo de hora
- WHEN se parsea el documento y se propaga hasta el registro de salida
- THEN el campo de hora es ausencia explícita en `DocumentoParseado` y en `RegistroAnonimizado`
- AND ningún valor de hora (incluida medianoche) queda registrado como si fuera una hora real

### Requirement: Hora ilegible va a cuarentena, no a ausencia silenciosa

Cuando el campo de hora existe en el documento pero su valor no puede parsearse contra el formato
esperado, el sistema MUST tratarlo como fallo de parseo y enviar el documento a cuarentena con un
motivo explícito. El sistema MUST NOT emitir ese caso como ausencia de hora: "el documento no trae
hora" y "el documento trae hora pero no se pudo leer" MUST ser estados distinguibles en el
resultado del pipeline.

#### Scenario: Hora presente pero con formato irreconocible

- GIVEN un laboratorio o ECG cuyo campo de hora está presente pero con un valor que no matchea
  ningún formato de hora soportado
- WHEN se parsea el documento
- THEN el documento se aparta a cuarentena con un motivo que identifica el campo de hora como causa
- AND el documento NO se publica con el campo de hora en ausencia, para no confundirse con un
  documento que genuinamente no trae hora

### Requirement: ECG conserva la hora capturada en el header

El sistema MUST conservar la hora del estudio con precisión de segundo tal como aparece en el
header del ECG, sin truncarla al convertir la fecha.

#### Scenario: ECG con hora completa en el header

- GIVEN un ECG cuyo header trae fecha y hora en formato `DD-MON-YYYY HH:MM:SS`
- WHEN se parsea el documento
- THEN `fecha_estudio` refleja únicamente la fecha
- AND el campo de hora refleja la hora con precisión de segundo, sin truncar

### Requirement: Laboratorio expone la hora de extracción como campo tipado

El sistema MUST promover la hora de extracción del laboratorio (rotulada `Hora de Extracción:` o
variantes ya reconocidas por el parser) a un campo de hora tipado con precisión de minuto. El
sistema MUST NOT dejar este valor dentro del mapa de campos adicionales sin tipo una vez
promovido.

#### Scenario: Laboratorio con hora de extracción rotulada

- GIVEN un laboratorio cuyo documento trae un campo `Hora de Extracción:` con un valor `HH:MM`
  legible
- WHEN se parsea el documento
- THEN el campo de hora tipado expone ese valor con precisión de minuto
- AND ese valor ya no aparece dentro de los campos adicionales sin tipo

### Requirement: Normalización de hora sin inferencia

La normalización de hora MUST seguir el mismo principio que `normalizar_fecha_iso`: aceptar solo
formatos explícitos ya presentes en el documento y rechazar cualquier valor que no matchee ninguno
de ellos. El sistema MUST NOT inferir, completar ni corregir una hora ambigua o parcial.

#### Scenario: Un valor de hora fuera de los formatos soportados se rechaza

- GIVEN un valor de hora que no matchea ningún formato explícito soportado
- WHEN se intenta normalizar ese valor
- THEN la normalización falla de forma explícita, sin producir un valor aproximado o inferido

### Requirement: Hora local sin conversión de huso

El sistema MUST registrar la hora tal como aparece en el documento, como hora local del instituto,
sin aplicar conversión ni inferencia de huso horario en ninguna etapa del pipeline.

#### Scenario: La hora se propaga sin transformación de huso

- GIVEN una hora extraída de un documento fuente
- WHEN esa hora se propaga hasta el registro de salida
- THEN el valor numérico de la hora es idéntico al del documento fuente, sin ajuste de huso

### Requirement: Procedencia citable y verificable en reconciliación

Cada hora extraída (ECG y laboratorio) MUST tener su propia `ReferenciaCampo`, igual que el resto
de los campos parseados. La reconciliación MUST poder verificar esa hora contra el texto del
documento fuente, con el mismo criterio de evidencia que aplica a los demás campos.

#### Scenario: La reconciliación verifica la hora contra el documento fuente

- GIVEN un documento parseado cuyo campo de hora tiene una `ReferenciaCampo` asociada
- WHEN se ejecuta la reconciliación de ese documento
- THEN el valor de hora se verifica contra el texto de la página referenciada
- AND la reconciliación falla si la hora no aparece como evidencia en esa página, con el mismo
  criterio de discrepancia/ambigüedad que el resto de los campos
