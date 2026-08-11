# Especificación: Ingesta clínica anonimizada

## Propósito
Procesar PDFs clínicos sin conservar contenido identificable ni crudo.

## Requisitos

### Requisito: Procesamiento transitorio
El sistema DEBE (MUST: obligatorio) leer el PDF sólo transitoriamente y completar extracción, anonimización y controles antes de habilitar datos.

#### Escenario: Documento aprobado
- DADO un PDF clínico
- CUANDO supera privacidad y calidad aprobada
- ENTONCES habilita sólo observaciones permitidas y trazabilidad técnica

#### Escenario: Copia sensible
- DADO cualquier etapa
- CUANDO se intenta persistir PDF, texto crudo, PII/PHI o contenido sensible en temporales, colas o logs
- ENTONCES el sistema DEBE impedirlo

### Requisito: Controles y decisión
El sistema DEBE ejecutar anonimización, validación residual independiente y política de calidad por documento antes de persistir.

#### Escenario: PII o calidad no aprobada
- DADO PII residual, campos no verificados o controles incompletos
- CUANDO se evalúa el documento
- ENTONCES DEBE bloquear la persistencia clínica y registrar sólo estado y métricas técnicas no identificantes
