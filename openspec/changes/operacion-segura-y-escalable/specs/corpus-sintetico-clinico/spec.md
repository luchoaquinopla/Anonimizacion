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

## ADDED Requirements (cambio `senal-ecg-y-dataset-vinculado`)

### Requirement: Generación de trazos sintéticos de ECG con oráculo conocido
El generador sintético MUST dibujar trazos vectoriales de ECG (12 derivaciones + tira de
ritmo V1) usando el mismo layout geométrico medido (4 columnas de 3, offsets 0/2,5/5/7,5 s,
1238 muestras por derivación a 500 Hz, tira de ritmo de 5000 muestras, 4 pulsos de
calibración de 60 muestras, trazo negro ancho≈0,43, escala 25 mm/s y 10 mm/mV), MUST
conservar la señal fuente como oráculo para comparar contra la señal extraída.

#### Scenario: ECG sintético con oráculo
- GIVEN una semilla fija de generación
- WHEN se genera un PDF sintético de ECG
- THEN el PDF contiene trazos vectoriales con el layout geométrico esperado
- AND el oráculo guarda la señal fuente en mV por derivación para comparación posterior
