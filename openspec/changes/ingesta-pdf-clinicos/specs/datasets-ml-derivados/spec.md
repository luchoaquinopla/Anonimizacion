# Especificación: Datasets ML derivados

## Propósito
Producir conjuntos reproducibles de features sin alterar la fuente clínica aprobada.

## Requisitos

### Requisito: Derivación versionada
El sistema DEBE (MUST: obligatorio) derivar features desde observaciones aprobadas y registrar versión, definición y criterio de inclusión.

#### Escenario: Generación
- DADAS observaciones aprobadas y una definición versionada
- CUANDO se genera un dataset
- ENTONCES contiene features reproducibles y referencia a su definición

#### Escenario: Fuente no verificable
- DADA una observación con estado distinto de verified o bloqueada
- CUANDO se construye un dataset
- ENTONCES el sistema DEBE excluirla

### Requisito: Target opcional
El sistema DEBE permitir datasets sin etiqueta de predicción.

#### Escenario: Exploración inicial
- DADO que no se definió una predicción
- CUANDO se publica un dataset
- ENTONCES contiene features sin target ni modifica la fuente
