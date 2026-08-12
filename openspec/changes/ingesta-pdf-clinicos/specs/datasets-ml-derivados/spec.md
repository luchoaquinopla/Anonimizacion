# Especificación: Exclusión de datasets ML derivados

## Propósito

Garantizar que esta entrega no produzca, conserve ni publique *features*, datasets o etiquetas de aprendizaje automático a partir de los PDFs procesados.

En esta especificación, DEBE corresponde a MUST (obligatorio) y NO DEBE corresponde a MUST NOT (prohibido) según RFC 2119.

## Requisitos

### Requisito: Ausencia de productos ML

El sistema NO DEBE definir un *target*, derivar o generar *features*, materializar datasets ML ni persistir resultados destinados a aprendizaje automático.

#### Escenario: Observaciones transitorias disponibles

- DADO que el procesamiento en memoria produjo observaciones clínicas transitorias
- CUANDO el archivo completa su tratamiento
- ENTONCES el sistema NO DEBE transformar esas observaciones en *features* o datasets
- Y DEBE descartarlas conforme a las restricciones de ingesta

#### Escenario: Solicitud de dataset o target

- DADO una solicitud para publicar un dataset, una definición de *features* o una etiqueta de predicción
- CUANDO se evalúa dentro de esta entrega
- ENTONCES el sistema NO DEBE producir ese artefacto
- Y la capacidad DEBE permanecer fuera del alcance hasta una aprobación separada

### Requisito: Ausencia de persistencia para uso futuro

El sistema NO DEBE conservar datos clínicos originales o anonimizados, estados de extracción ni resultados intermedios con el propósito de habilitar un uso ML posterior.

#### Escenario: Retención preventiva

- DADO un dato transitorio que podría ser útil para una futura iniciativa ML
- CUANDO termina el tratamiento del archivo
- ENTONCES el sistema DEBE descartarlo
- Y NO DEBE crear almacenamiento, exportación ni registro para recuperarlo posteriormente
