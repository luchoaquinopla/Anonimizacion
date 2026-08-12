# Especificación: Observaciones clínicas transitorias

## Propósito

Resolver los campos clínicos esperados con trazabilidad interna durante la extracción, sin convertirlos en una salida de producto ni conservarlos después del tratamiento del archivo.

En esta especificación, DEBE corresponde a MUST (obligatorio) y NO DEBE corresponde a MUST NOT (prohibido) según RFC 2119.

## Requisitos

### Requisito: Inventario y resolución transitoria

El sistema DEBE usar un inventario versionado de campos esperados por familia y adaptador. Durante el tratamiento en memoria, cada campo esperado DEBE concluir exactamente como `verified`, `not_present`, `missing`, `ambiguous`, `malformed` o `truncated`, con un motivo técnico interno no identificante.

#### Escenario: Campo verificado

- DADO un campo esperado con valor y unidad válidos
- CUANDO el adaptador lo valida en memoria
- ENTONCES DEBE clasificarlo como `verified` para los controles del archivo
- Y NO DEBE exponerlo en la interfaz ni persistirlo

#### Escenario: Omisión

- DADO un campo del inventario sin resolución confiable
- CUANDO finaliza la extracción
- ENTONCES DEBE clasificarlo como `missing`
- Y NO DEBE omitirlo silenciosamente de los controles de completitud

### Requisito: Validación de campo

El sistema DEBE validar valor, integridad, análisis sintáctico, unidad y unicidad antes de declarar un campo `verified`.

#### Escenario: Valor defectuoso

- DADO un valor truncado, dañado, inválido o con unidad incompatible
- CUANDO se evalúa en memoria
- ENTONCES DEBE clasificarlo como `truncated` o `malformed`, nunca como `verified`

#### Escenario: Candidatos múltiples

- DADO candidatos sin una regla resolutiva
- CUANDO se evalúa el campo
- ENTONCES DEBE clasificarlo como `ambiguous`
- Y NO DEBE seleccionar ni conservar un valor como verificado

#### Escenario: Ausencia legítima

- DADO un campo opcional que no figura en el documento
- CUANDO su regla confirma la ausencia
- ENTONCES DEBE clasificarlo como `not_present`, no como `missing`

### Requisito: Prohibición de persistencia e intercambio clínico

Las observaciones, sus valores y su procedencia DEBEN descartarse antes de completar el tratamiento de cada archivo. El sistema NO DEBE persistirlas en SQL, JSON, archivos, temporales, registros ni otro almacenamiento, y NO DEBE devolverlas a la interfaz.

#### Escenario: Campo resuelto al terminar el archivo

- DADO cualquier observación transitoria, incluso una clasificada como `verified`
- CUANDO el archivo alcanza un resultado técnico terminal
- ENTONCES el sistema DEBE descartar el valor, unidad, rango, procedencia y estado
- Y sólo DEBE devolver el código técnico seguro permitido para el archivo
