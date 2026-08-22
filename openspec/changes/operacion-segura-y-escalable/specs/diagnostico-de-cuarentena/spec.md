# Diagnóstico de cuarentena Specification

## Requirements

### Requirement: Registro seguro
El sistema MUST registrar tipo, etapa, regla y código de rechazo sin PII ni texto clínico crudo.

#### Scenario: Eco rechazado
- GIVEN un eco que falla validación
- WHEN entra en cuarentena
- THEN registra un código seguro correlacionable

### Requirement: Reproducción mínima
El sistema MUST reproducir un rechazo con fixture sintética o anonimizada y prueba automatizada.

#### Scenario: Caso confirmado
- GIVEN un diagnóstico con fixture aprobada
- WHEN corre la prueba focalizada
- THEN reproduce el resultado sin el PDF original

### Requirement: Incertidumbre
El sistema MUST conservar en cuarentena un eco no verificable.

#### Scenario: Variante desconocida
- GIVEN una variante no cubierta
- WHEN se procesa
- THEN no se publica como válida
