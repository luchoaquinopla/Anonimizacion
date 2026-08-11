# Especificación: Observaciones clínicas

## Propósito
Conservar datos clínicos permitidos, consultables y trazables sin retener fuente sensible.

## Requisitos

### Requisito: Inventario y resolución
El sistema DEBE (MUST: obligatorio) usar un inventario versionado de campos esperados por familia y adaptador. Cada campo esperado DEBE concluir exactamente como verified, not_present, missing, ambiguous, malformed o truncated, con motivo o código técnico no identificante.

#### Escenario: Campo verificado
- DADO un campo esperado con valor y unidad válidos
- CUANDO el adaptador lo valida
- ENTONCES lo clasifica verified con procedencia y versión

#### Escenario: Omisión
- DADO un campo del inventario sin resolución confiable
- CUANDO finaliza la extracción
- ENTONCES lo clasifica missing; no puede omitirse silenciosamente

### Requisito: Validación de campo
El sistema DEBE validar valor, integridad, parseo, unidad y unicidad antes de declarar verified.

#### Escenario: Valor defectuoso
- DADO un valor truncado, dañado, inválido o con unidad incompatible
- CUANDO se evalúa
- ENTONCES lo clasifica truncated o malformed, nunca verified

#### Escenario: Candidatos múltiples
- DADO candidatos sin regla resolutiva
- CUANDO se evalúa el campo
- ENTONCES lo clasifica ambiguous y no persiste valor verificado

### Requisito: Registro e intercambio
El sistema DEBE persistir en SQL sólo campos verified de documentos aprobados, con tipo, código/nombre, valor, unidad, rango si existe, calidad y procedencia técnica. El JSON anonimizado sólo incluye datos permitidos y no sustituye SQL.

#### Escenario: Persistencia
- DADO un documento aprobado y campo verified
- CUANDO se persiste o serializa
- ENTONCES conserva atributos permitidos y versiones de extractor, inventario y esquema
