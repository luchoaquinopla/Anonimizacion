# Orquestación de episodios Specification

## Requirements

### Requirement: Reanudación durable
El sistema MUST inventariar estados de archivo y reanudar sin duplicar resultados.

#### Scenario: Interrupción
- GIVEN una corrida parcial
- WHEN se reinicia
- THEN continúa desde el último estado confirmado
- AND no duplica episodios publicados

### Requirement: Asociación temporal por tipo
El sistema MUST asociar por identidad pseudónima y ventana configurada por tipo de estudio.

#### Scenario: Candidato válido
- GIVEN documentos coincidentes dentro de la ventana aplicable
- WHEN se ensambla el episodio
- THEN los asocia correctamente

#### Scenario: Asociación ambigua
- GIVEN candidatos igualmente válidos
- WHEN se ensambla el episodio
- THEN MUST enviarlo a cuarentena

### Requirement: Puerta de reconciliación
El sistema MUST reconciliar antes de anonimizar o publicar.

#### Scenario: Reconciliación fallida
- GIVEN datos inconsistentes o incompletos
- WHEN falla la reconciliación
- THEN el episodio queda en cuarentena
