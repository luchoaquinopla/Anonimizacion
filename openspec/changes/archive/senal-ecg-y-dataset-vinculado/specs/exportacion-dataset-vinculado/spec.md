# Exportación de Dataset Vinculado — Especificación

## Purpose

Producir, a partir de PostgreSQL, un dataset de episodios (ECG + laboratorio + eco del
mismo paciente, vinculados por `patient_id` y ventana de hasta 7 días) reproducible fuera
de la base, sin PII y con contrato declarado para el consumidor (`modelo-hvi`).

## Requirements

### Requirement: Exportación derivada de PostgreSQL como fuente de verdad
El sistema MUST generar la exportación (Parquet + manifiesto) leyendo exclusivamente de
PostgreSQL, sin escribir de vuelta a la base y sin que la exportación sea la fuente de
verdad del dataset.

#### Scenario: Exportación no muta la base
- GIVEN una base con episodios publicados
- WHEN se ejecuta el subcomando `exportar`
- THEN se generan archivos Parquet y un manifiesto
- AND ninguna fila de PostgreSQL se modifica como efecto de la exportación

### Requirement: Vinculación de episodio por paciente y ventana de 7 días
El sistema MUST agrupar en un mismo episodio exportado los documentos (ECG, laboratorio,
eco) que comparten `patient_id` y cuya diferencia de fecha es de hasta 7 días, y MUST
marcar explícitamente qué campos de cada episodio están incompletos.

#### Scenario: Episodio con los 3 documentos dentro de la ventana
- GIVEN un ECG, un laboratorio y un eco del mismo `patient_id` con fechas dentro de 7 días
- WHEN se exporta el dataset
- THEN los tres quedan agrupados en un único episodio del Parquet
- AND el episodio se marca como completo

#### Scenario: Episodio incompleto
- GIVEN un episodio con laboratorio pero sin ECG disponible
- WHEN se exporta el dataset
- THEN el episodio se incluye con el campo de ECG marcado como faltante
- AND no se descarta el episodio por estar incompleto

### Requirement: Manifiesto de contrato para el consumidor
El sistema MUST emitir un manifiesto que declare la frecuencia de muestreo (500 Hz), el
orden de las 12 derivaciones + tira de ritmo, y las ventanas de vinculación usadas, para
que `modelo-hvi` pueda decimar (×2) sin transformación adicional.

#### Scenario: Consumidor decimando ×2
- GIVEN un manifiesto exportado con señal a 500 Hz
- WHEN el consumidor decima ×2 según el manifiesto
- THEN obtiene 619 muestras por derivación, coincidiendo con `EsquemaPdf`
- AND no aplica ninguna otra transformación

### Requirement: Cero PII en la exportación
El sistema MUST NOT incluir nombre, DNI, ni fecha de nacimiento en ningún archivo ni
metadata de la exportación. El único identificador de paciente permitido es el
`patient_id` (HMAC).

#### Scenario: Auditoría de PII sobre la exportación
- GIVEN un dataset exportado completo
- WHEN se ejecuta el verificador de PII sobre los archivos generados
- THEN se reportan 0 coincidencias de nombre, DNI o fecha de nacimiento
