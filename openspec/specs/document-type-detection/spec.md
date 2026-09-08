# Detección de Tipo de Documento — Especificación

## Purpose

Clasificar el layout de un PDF extraído (ECG, laboratorio o ecocardiograma) y despachar al
parser correspondiente mediante patrón Strategy.

## Requirements

### Requirement: Clasificación por marcadores de texto
El sistema MUST clasificar el documento como uno de los 3 tipos conocidos (ECG Mortara,
laboratorio, ecocardiograma) en base a marcadores textuales del header extraído, antes de
invocar cualquier parser.

#### Scenario: Clasificación correcta de los 3 tipos
- GIVEN un texto extraído de cada uno de los 3 tipos de documento
- WHEN se ejecuta la detección de tipo
- THEN cada documento se clasifica con el tipo correcto correspondiente

### Requirement: Despacho vía Strategy sin lógica monolítica
El sistema MUST despachar al parser correspondiente usando un patrón Strategy/Plugin
(un parser por tipo detrás de una interfaz común), sin un `if/elif` monolítico por tipo.

#### Scenario: Documento no reconocido
- GIVEN un PDF cuyo texto no coincide con ninguno de los 3 layouts conocidos
- WHEN se ejecuta la detección de tipo
- THEN el sistema marca el documento como "tipo no reconocido" con fallo explícito
- AND NO intenta forzar un parser por defecto sobre el documento
