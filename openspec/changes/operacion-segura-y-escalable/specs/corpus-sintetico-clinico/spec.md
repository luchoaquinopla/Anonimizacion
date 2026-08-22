# Corpus sintético clínico Specification

## Requirements

### Requirement: Generación reproducible
El sistema MUST generar localmente PDFs sintéticos de ECG, laboratorio y eco, con semilla y oráculo.

#### Scenario: Misma semilla
- GIVEN idéntica configuración y semilla
- WHEN se genera dos veces
- THEN produce el mismo corpus lógico y oráculo

### Requirement: Cobertura crítica
El corpus MUST incluir casos válidos, faltantes, ambiguos, corruptos y con PII sintética.

#### Scenario: Validación masiva
- GIVEN un corpus de carga conocido
- WHEN corre el pipeline
- THEN coincide con el oráculo o la cuarentena esperada

### Requirement: Aislamiento
El generador MUST NOT usar PII real ni conectividad externa.

#### Scenario: Sin red
- GIVEN un entorno aislado
- WHEN se genera el corpus
- THEN finaliza sólo con datos locales
