# Vinculación Pseudónima — Especificación

## Purpose

Generar un `patient_id` pseudónimo estable a partir del DNI, antes de descartar la PII,
para permitir el cruce entre ECG, laboratorio y ecocardiograma del mismo paciente sin
persistir el DNI real.

## Requirements

### Requirement: Generación determinística de patient_id antes de descartar PII
El sistema MUST generar `patient_id` mediante HMAC(DNI, salt) **antes** de que el DNI en
texto plano sea descartado del pipeline. El mismo DNI con el mismo salt MUST producir
siempre el mismo `patient_id` (determinismo).

#### Scenario: Mismo DNI en dos documentos distintos
- GIVEN dos documentos (laboratorio y ecocardiograma) con el mismo DNI real
- WHEN se genera el patient_id para cada uno
- THEN ambos documentos obtienen exactamente el mismo patient_id

### Requirement: DNI real nunca persiste tras la pseudonimización
El sistema MUST NOT persistir el DNI en texto plano en ningún artefacto posterior a la
generación del patient_id (ni en el dataset de salida, ni en logs, ni en almacenamiento
intermedio).

#### Scenario: Verificación de ausencia de DNI real
- GIVEN el pipeline completo ejecutado sobre un documento
- WHEN se inspecciona cualquier artefacto generado después de la etapa de pseudonimización
- THEN el DNI en texto plano no aparece en ningún campo ni log

### Requirement: Salt (pepper) almacenado separado del dataset
El salt (llamado "pepper" en el código, `pseudonimizacion/almacen_pepper.py`) usado para el
HMAC MUST almacenarse separado del dataset de features anonimizado, con acceso restringido,
y MUST NOT persistirse en el repositorio ni loguearse.

**Resuelto** (originalmente BLOQUEADO pendiente de sdd-design, pregunta abierta #1 de
storage; ver `design.md`, "Almacenamiento del pepper"): el mecanismo concreto es variable de
entorno `ANONIMIZACION_PEPPER`, o alternativamente `ANONIMIZACION_PEPPER_ARCHIVO` apuntando
a un archivo local cifrado en reposo (responsabilidad de infraestructura). Si ninguna fuente
está configurada, `obtener_pepper()` lanza `ErrorPepperNoConfigurado` y el pipeline no
arranca.

#### Scenario: Salt no accesible junto al dataset
- GIVEN el dataset anonimizado final
- WHEN se accede al almacén donde vive el dataset
- THEN el salt no se encuentra en ese mismo almacén ni junto a esos archivos

### Requirement: Vinculación por ventana de ±7 días
El sistema MUST vincular bajo el mismo patient_id todos los documentos (ECG, laboratorio,
ecocardiograma) cuya diferencia de fecha respecto a cualquier otro documento del mismo
patient_id sea de hasta 7 días inclusive, en cualquier dirección temporal.

#### Scenario: Documentos dentro de la ventana
- GIVEN un ECG con fecha D y un laboratorio del mismo paciente con fecha D+7
- WHEN se procesan ambos documentos
- THEN ambos quedan vinculados bajo el mismo patient_id

#### Scenario: Documentos fuera de la ventana
- GIVEN un ECG con fecha D y un ecocardiograma del mismo paciente con fecha D+8
- WHEN se procesan ambos documentos
- THEN el sistema NO los vincula automáticamente como parte del mismo evento clínico
  vinculado (aunque comparten patient_id por ser el mismo paciente)
