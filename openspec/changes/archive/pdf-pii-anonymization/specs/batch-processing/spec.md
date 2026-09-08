# Procesamiento por Lotes — Especificación

## Purpose

Procesar el corpus completo (~100.000 documentos) vía cola async y worker pool, con
reintentos y trazabilidad sin exponer PII, sin que el fallo de un documento aborte el lote.

## Requirements

### Requirement: Aislamiento de fallos por documento
El sistema MUST procesar cada documento de forma aislada dentro de la cola async, de modo
que el fallo de un documento (layout no reconocido, PDF corrupto, error de parsing) NO
detiene el procesamiento del resto del lote.

#### Scenario: Un documento con layout no reconocido en un lote grande
- GIVEN un lote de 1000 documentos donde 1 tiene un layout no reconocido
- WHEN se ejecuta el procesamiento del lote
- THEN los 999 documentos restantes se procesan y emiten normalmente
- AND el documento fallido queda registrado con estado de fallo explícito

### Requirement: Reintentos ante fallos transitorios
El sistema SHOULD reintentar automáticamente un documento que falló por un error
transitorio (ej. error de I/O temporal), con backoff, antes de marcarlo como fallo
definitivo.

#### Scenario: Reintento exitoso tras fallo transitorio
- GIVEN un documento que falla en el primer intento por un error transitorio de I/O
- WHEN el worker reintenta el procesamiento
- THEN el documento se procesa exitosamente en el reintento
- AND queda registrado como éxito, no como fallo

### Requirement: Trazabilidad sin PII
El sistema MUST registrar en los logs de trazabilidad del lote únicamente metadata no
sensible (id de documento, tipo detectado, estado de resultado, timestamp), y MUST NOT
registrar PII cruda del contenido del documento en ningún punto del procesamiento por
lotes.

#### Scenario: Log de lote inspeccionable
- GIVEN un lote de 100 documentos procesados, incluyendo casos de éxito y de fallo
- WHEN se inspecciona el log de trazabilidad del lote
- THEN cada entrada contiene solo id de documento, tipo y estado
- AND ninguna entrada contiene nombre, DNI, ni fecha de nacimiento
