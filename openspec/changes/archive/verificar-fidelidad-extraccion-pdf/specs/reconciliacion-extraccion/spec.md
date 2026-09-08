# Especificación de reconciliación de extracción

## Propósito

Garantizar fidelidad y completitud entre un PDF de ECG, laboratorio o eco y su registro estructurado antes de detectar PII, anonimizar o persistir. La comprobación modelo→PDF por sí sola es insuficiente: también se debe detectar contenido clínico reconocido que el modelo omitió.

## Requisitos

### Requirement: Reconciliación previa obligatoria

El sistema MUST reconciliar después del parseo y antes de detección de PII, pseudonimización y persistencia clínica. Solo un documento aprobado MAY continuar.

#### Scenario: Registro aprobado
- GIVEN un documento cuya igualdad y cobertura están aprobadas
- WHEN termina la reconciliación
- THEN el pipeline MUST habilitar la detección de PII

#### Scenario: Registro rechazado
- GIVEN un fallo de igualdad o cobertura
- WHEN el pipeline procesa el documento
- THEN MUST NOT detectar PII ni persistir salida clínica

### Requirement: Igualdad y procedencia por campo

El sistema MUST comprobar que cada valor estructurado requerido tenga una evidencia única, identificada y semánticamente igual en el PDF. Solo MUST aceptar normalizaciones explícitas; MUST NOT modificar unidad, signo, precisión ni asociación campo-valor.

#### Scenario: Valor respaldado
- GIVEN un valor estructurado y su evidencia única normalizada
- WHEN se reconcilian
- THEN el campo MUST aprobarse

#### Scenario: Evidencia ausente, ambigua o discrepante
- GIVEN un valor sin evidencia, con múltiples candidatas o diferente de ella
- WHEN se reconcilia
- THEN el documento MUST fallar con el código correspondiente

### Requirement: Inventario independiente de cobertura

El sistema MUST derivar por tipo documental un inventario independiente de campos clínicos reconocibles desde el PDF, sin depender de los valores ya emitidos por el parser. El inventario MUST distinguir campos obligatorios, colecciones y texto no clínico permitido.

#### Scenario: ECG completo
- GIVEN un ECG con etiquetas y medidas reconocibles
- WHEN se compara inventario y modelo
- THEN cada medida reconocida MUST corresponder a un campo estructurado una sola vez

#### Scenario: Medida ECG omitida
- GIVEN una medida reconocible en el PDF que no está en el modelo
- WHEN se valida cobertura
- THEN el documento MUST fallar por cobertura incompleta

### Requirement: Cobertura uno-a-uno de colecciones

El sistema MUST exigir correspondencia uno-a-uno entre evidencia clínica inventariada y valor estructurado. Para colecciones MUST validar cardinalidad y ordinal, de modo que filas o secciones repetidas no se oculten por coincidir en nombre o valor.

#### Scenario: Fila de laboratorio omitida
- GIVEN un laboratorio con analitos reconocibles y una fila no emitida
- WHEN se valida la colección
- THEN MUST fallar por cobertura incompleta indicando el ordinal seguro

#### Scenario: Sección de eco duplicada u omitida
- GIVEN un eco con medidas o secciones reconocibles
- WHEN su cardinalidad u orden no coincide con el modelo
- THEN MUST fallar por cobertura incompleta o ambigüedad

### Requirement: Whitelist de texto no clínico

El sistema MUST ignorar únicamente texto declarado en una whitelist explícita por tipo documental, como encabezados visuales o boilerplate. Todo texto clínico reconocible que no tenga destino estructurado MUST causar fallo; texto desconocido MUST NOT ignorarse implícitamente.

#### Scenario: Texto permitido
- GIVEN texto de formato incluido en la whitelist
- WHEN se crea el inventario
- THEN MUST NOT requerir valor estructurado

#### Scenario: Texto clínico sin destino
- GIVEN texto clínico reconocible fuera de la whitelist
- WHEN se valida cobertura
- THEN MUST fallar por cobertura incompleta

### Requirement: Cuarentena segura y pruebas

Ante fallo, el sistema MUST enviar el documento a cuarentena no reintentable con solo identificador técnico, tipo, etapa, código, campo y localización no sensible. MUST NOT guardar PII, texto ni valores clínicos crudos. Las pruebas sintéticas MUST cubrir igualdad, cobertura completa, omisiones y cardinalidad para ECG, laboratorio y eco.

#### Scenario: Cuarentena por cobertura incompleta
- GIVEN un campo, fila o sección omitida
- WHEN falla la reconciliación
- THEN cuarentena MUST excluir contenido sensible
