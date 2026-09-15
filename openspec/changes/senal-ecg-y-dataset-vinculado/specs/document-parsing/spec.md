# Delta para Parsing de Documentos

## MODIFIED Requirements

### Requirement: Parser de ECG tolerante a advertencias del equipo
El sistema MUST parsear el header de ECG (nombre completo, ID interno de estudio,
fecha/hora, institución, edad, sexo, técnico, médico derivante) y las medidas
(Vent. rate, PR interval, QRS duration, QT/QTc, ejes P-R-T). El sistema MUST tolerar
advertencias propias del equipo (ej. "PID / NAME MISMATCH") sin abortar el parsing.
El registro de ECG MUST incluir un campo de señal opcional, poblado por
`extraccion-senal-ecg`; cuando la señal no valida geométricamente, el registro MUST
publicarse con `ecg.senal` en `campos_no_extraidos` en lugar de fallar el parsing.
(Previously: no existía ningún campo de señal en el modelo de ECG parseado.)

#### Scenario: ECG con advertencia de equipo
- GIVEN un PDF de ECG que contiene el texto "PID / NAME MISMATCH"
- WHEN se ejecuta el parser de ECG
- THEN el documento se parsea exitosamente
- AND la advertencia no genera un fallo del parser

#### Scenario: ECG con señal válida
- GIVEN un PDF de ECG cuyo layout de trazos valida geométricamente
- WHEN se ejecuta el parser de ECG
- THEN el registro tipado incluye la señal calibrada junto al header y las medidas

#### Scenario: ECG con señal que no valida
- GIVEN un PDF de ECG cuyo layout de trazos no valida geométricamente
- WHEN se ejecuta el parser de ECG
- THEN el registro tipado se produce igual, sin campo de señal poblado
- AND `ecg.senal` queda listado en `campos_no_extraidos`
