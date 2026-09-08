# Parsing de Documentos — Especificación

## Purpose

Parsear cada tipo de documento a un modelo tipado, usando los campos reales confirmados
por análisis de PDFs de muestra (ver `sdd/pdf-pii-anonymization/document-analysis`).

## Requirements

### Requirement: Parser de laboratorio con reconciliación multi-página
El sistema MUST parsear el header de laboratorio (Apellido y Nombre, DNI, F.Nacimiento,
Edad, Médico derivante, Nº Petición, Fecha, Hora de Extracción, Origen) y el cuerpo
(tabla de pruebas por sección — HEMATOLOGIA, HEMOSTASIA, QUÍMICA CLÍNICA, IONOGRAMA, etc.
— con Resultado Actual, Unidades, Valores de Referencia). El sistema MUST reconciliar el
header repetido en cada página en un único registro por Nº de Petición.

#### Scenario: Documento de laboratorio de 4 páginas
- GIVEN un PDF de laboratorio con header repetido en 4 páginas y mismo Nº de Petición
- WHEN se ejecuta el parser de laboratorio
- THEN se produce un único registro tipado con un solo header
- AND todas las secciones de pruebas de las 4 páginas quedan en el mismo registro

### Requirement: Parser de ecocardiograma
El sistema MUST parsear el header de ecocardiograma (Paciente, Documento, Nº de Estudio,
Fecha, Médico Solicitante, Peso, Altura, Superficie Corporal), la tabla de medidas
(AO, AI, DDVI, DSVI, FA, Septum, P. Posterior, etc.), el texto libre por sección
(motilidad segmentaria, válvulas, pericardio, flujos Doppler, conclusiones) y la firma
del médico informante (nombre + matrícula).

#### Scenario: Ecocardiograma completo
- GIVEN un PDF de ecocardiograma con todas las secciones presentes
- WHEN se ejecuta el parser de ecocardiograma
- THEN el modelo tipado contiene header, medidas, texto por sección y firma del informante

### Requirement: Parser de ECG tolerante a advertencias del equipo
El sistema MUST parsear el header de ECG (nombre completo, ID interno de estudio,
fecha/hora, institución, edad, sexo, técnico, médico derivante) y las medidas
(Vent. rate, PR interval, QRS duration, QT/QTc, ejes P-R-T). El sistema MUST tolerar
advertencias propias del equipo (ej. "PID / NAME MISMATCH") sin abortar el parsing.

#### Scenario: ECG con advertencia de equipo
- GIVEN un PDF de ECG que contiene el texto "PID / NAME MISMATCH"
- WHEN se ejecuta el parser de ECG
- THEN el documento se parsea exitosamente
- AND la advertencia no genera un fallo del parser
