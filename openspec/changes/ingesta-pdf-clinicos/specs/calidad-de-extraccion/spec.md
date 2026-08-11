# Especificación: Calidad de extracción

## Propósito
Medir completitud y confiabilidad antes de habilitar datos clínicos.

## Requisitos

### Requisito: Corpus, inventario y métricas
El sistema DEBE (MUST: obligatorio) evaluar cada adaptador versionado contra un corpus autorizado y anotado, usando su inventario de campos esperados. DEBE informar por familia, adaptador y campo: cobertura/recall, exactitud de valor y unidad, tasa de omisiones, rechazo y PII residual.

#### Escenario: Evaluación
- DADO un corpus con resultados esperados
- CUANDO se ejecuta un adaptador
- ENTONCES informa las métricas requeridas por familia, campo y versión

### Requisito: Umbrales y regresión
Los umbrales numéricos DEBEN acordarse con datos del corpus antes de producción. Una versión bajo un umbral DEBE ser no apta para persistencia productiva.

#### Escenario: Umbral ausente o incumplido
- DADA una versión sin umbral aprobado o con una métrica inferior
- CUANDO se intenta habilitar en producción
- ENTONCES el sistema DEBE rechazarla

### Requisito: Decisión por documento
El sistema DEBE evaluar los estados de todos sus campos esperados con la política aprobada.

#### Escenario: Campo no verificable
- DADO un campo truncado, dañado, ambiguo o faltante requerido
- CUANDO se evalúa el documento
- ENTONCES DEBE rechazar su persistencia clínica y conservar sólo métricas técnicas permitidas

#### Escenario: Ausencia legítima
- DADO un campo opcional que no figura en el documento
- CUANDO su regla confirma la ausencia
- ENTONCES lo registra como not_present, no como omisión
