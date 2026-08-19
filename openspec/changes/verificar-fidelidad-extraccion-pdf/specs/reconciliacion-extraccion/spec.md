# Especificación de reconciliación de extracción

## Propósito

Garantizar que el registro estructurado de ECG, laboratorio o ecocardiograma coincida fielmente con su contenido fuente antes de detectar PII, anonimizar o persistir datos.

## Requisitos

### Requirement: Reconciliación previa obligatoria

El sistema MUST ejecutar la reconciliación después del parseo y antes de la detección de PII, pseudonimización y cualquier persistencia de salida.

#### Scenario: Registro aprobado

- GIVEN un PDF reconocido y un registro parseado con evidencia suficiente
- WHEN todos los campos requeridos se reconcilian
- THEN el pipeline MUST habilitar la etapa de detección de PII
- AND la persistencia posterior MAY continuar

#### Scenario: Registro no aprobado

- GIVEN un resultado de reconciliación fallido
- WHEN el pipeline procesa el documento
- THEN MUST NOT detectar PII, pseudonimizar ni persistir su salida clínica

### Requirement: Igualdad por campo

El sistema MUST comparar cada campo requerido del registro tipado contra la evidencia procedente del texto del PDF, según reglas declaradas para ECG, laboratorio y eco. La igualdad MUST preservar el significado del valor.

#### Scenario: Coincidencia exacta

- GIVEN un campo requerido y evidencia con la misma representación normalizada
- WHEN se reconcilia el campo
- THEN el campo MUST aprobarse

#### Scenario: Cambio semántico

- GIVEN un campo tipado cuyo valor difiere de su evidencia
- WHEN se reconcilia el campo
- THEN el documento MUST fallar con código de discrepancia

### Requirement: Normalizaciones permitidas

El sistema MUST aceptar únicamente equivalencias de formato explícitamente definidas por campo y tipo documental; MUST NOT aplicar transformaciones que cambien significado clínico, unidad, signo, precisión o asociación del campo.

#### Scenario: Equivalencia explícita

- GIVEN dos representaciones equivalentes bajo la regla del campo
- WHEN se reconcilian
- THEN el campo MUST aprobarse

#### Scenario: Conversión no autorizada

- GIVEN una diferencia no cubierta por una regla explícita
- WHEN se reconcilia el campo
- THEN el documento MUST fallar como discrepancia

### Requirement: Ausencia y ambigüedad

El sistema MUST rechazar el documento si falta un campo requerido, falta su evidencia, hay más de una evidencia candidata sin regla que la desambigüe, o la procedencia no identifica su fuente.

#### Scenario: Campo o evidencia ausente

- GIVEN un campo requerido o su evidencia inexistente
- WHEN se reconcilia el documento
- THEN MUST fallar con código de ausencia

#### Scenario: Evidencia ambigua

- GIVEN múltiples candidatas para un mismo campo sin selección determinística
- WHEN se reconcilia el documento
- THEN MUST fallar con código de ambigüedad

### Requirement: Cuarentena segura y trazabilidad

Ante cualquier fallo, el sistema MUST derivar el documento a cuarentena como error no reintentable y conservar solo identificador técnico, tipo documental, etapa, código, identificador de campo y localización no sensible. MUST NOT almacenar, registrar ni exponer PII, texto fuente ni valores clínicos crudos; la evidencia verificable MUST usar exclusivamente metadatos permitidos y huellas HMAC.

#### Scenario: Discrepancia aislada

- GIVEN una discrepancia de reconciliación
- WHEN se registra la cuarentena
- THEN MUST incluir etapa, código y campo
- AND MUST excluir PII y valores o texto crudos

#### Scenario: Auditoría permitida

- GIVEN un documento en cuarentena
- WHEN un proceso autorizado consulta su metadato de reconciliación
- THEN MAY verificar la huella y localización no sensible
- AND MUST NOT recuperar contenido clínico ni PII desde esa traza

### Requirement: Cobertura verificable

El sistema MUST contar con pruebas sintéticas para ECG, laboratorio y eco que cubran coincidencia, normalización permitida, ausencia, discrepancia y ambigüedad. Las pruebas MUST NOT usar PDFs reales ni PII real.

#### Scenario: Suite por tipo documental

- GIVEN fixtures sintéticas de los tres tipos documentales
- WHEN se ejecuta la suite de reconciliación
- THEN MUST validar cada resultado esperado sin acceder a PDFs reales

