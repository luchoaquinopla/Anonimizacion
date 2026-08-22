# Bundles anonimizados Specification

## Requirements

### Requirement: Bundle pseudónimo
El sistema MUST publicar episodios aprobados con identificadores pseudónimos, manifiesto y datos seguros.

#### Scenario: Episodio aprobado
- GIVEN un episodio reconciliado y anonimizado
- WHEN se publica
- THEN crea su bundle
- AND no incluye PDFs, DNI, nombres ni secretos

### Requirement: Proyección Parquet idempotente
El sistema MUST generar una proyección trazable sin duplicar filas.

#### Scenario: Reintento
- GIVEN un episodio ya proyectado
- WHEN se republica
- THEN conserva una única proyección vigente

### Requirement: Separación de originales
El sistema MUST mantener originales y cuarentena fuera del dataset anonimizado.

#### Scenario: Inspección
- GIVEN acceso al dataset
- WHEN se inspecciona
- THEN no contiene PDFs originales
