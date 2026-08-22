# Portal de corridas Specification

## Requirements

### Requirement: Inicio seguro de corrida
El sistema MUST iniciar corridas sólo sobre ubicaciones autorizadas y registrar identificador, estado y hora.

#### Scenario: Inicio válido
- GIVEN un operador y ubicación autorizados
- WHEN inicia una corrida
- THEN registra una corrida pendiente única
- AND el navegador no recibe PDFs ni secretos

#### Scenario: Ubicación no autorizada
- GIVEN una ubicación no permitida
- WHEN se solicita una corrida
- THEN MUST rechazarla sin registrar PII

### Requirement: Consulta de progreso
El sistema MUST mostrar progreso y cuarentenas agregadas sin PII.

#### Scenario: Consulta
- GIVEN una corrida existente
- WHEN el operador la consulta
- THEN visualiza estados y motivos agregados
