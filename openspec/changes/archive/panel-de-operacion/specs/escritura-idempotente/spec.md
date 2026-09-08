# Especificación: escritura idempotente (delta)

Capacidad modificada. Extiende la garantía existente en
`openspec/changes/escritura-idempotente/specs/escritura-idempotente/spec.md` —hoy sólo cubre
estudio y las tablas de medición— para que también cubra cuarentena. El requisito se fija en
términos de comportamiento observable, no de una restricción de esquema concreta: qué columnas
forman la clave es decisión de diseño.

## Requisitos agregados

### Requisito: reprocesar la misma corrida no duplica el apartado

Reprocesar un documento que ya fue apartado dentro de la misma corrida, con el mismo desenlace,
**MUST NOT** aumentar el conteo de documentos apartados de esa corrida.

Dos corridas distintas **MAY** registrar cada una su propio desenlace de cuarentena para el mismo
documento. Eso **MUST** contarse como historial —una fila por corrida—, no como duplicado.

La operación **MUST** completarse sin error: reprocesar es un caso normal de operación.

#### Escenario: reprocesar la misma corrida no duplica

- **Given** un documento ya apartado dentro de una corrida, con un motivo determinado
- **When** esa misma corrida se reprocesa y el documento vuelve a fallar con el mismo motivo
- **Then** el conteo de apartados de esa corrida sigue siendo el mismo que antes de reprocesar

#### Escenario: corridas distintas no se pisan

- **Given** un documento apartado en una corrida
- **When** el mismo documento se procesa como parte de una corrida distinta y también falla
- **Then** cada corrida tiene su propio registro de apartado para ese documento
- **And** el conteo de cada corrida es correcto de forma independiente

#### Escenario: el reporte de cuarentena no sobrecuenta tras reprocesar

- **Given** una corrida con un documento ya apartado
- **When** esa corrida se reprocesa por completo sobre el mismo corpus
- **Then** el reporte de cuarentena y el embudo de esa corrida siguen mostrando un único apartado
  para ese documento
