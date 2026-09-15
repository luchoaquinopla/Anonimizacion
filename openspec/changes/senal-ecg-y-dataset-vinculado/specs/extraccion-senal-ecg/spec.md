# Extracción de Señal de ECG — Especificación

## Purpose

Recuperar la señal digital del trazado de ECG a partir de los trazos vectoriales del PDF
(`get_drawings()`), calibrada en mV, sin leer nunca texto del documento.

## Requirements

### Requirement: Extracción vectorial de las 12 derivaciones + tira de ritmo
El sistema MUST extraer, usando sólo `get_drawings()` (nunca texto ni OCR), las 12
derivaciones estándar (1238 muestras cada una) más la tira de ritmo V1 (5000 muestras),
a 500 Hz, distribuidas en 4 columnas de 3 derivaciones con offsets de tiempo 0/2,5/5/7,5 s.
El sistema MUST resolver el eje temporal a partir de la altura del rectángulo de trazo sin
rotar, dado que la página se exporta rotada 90°.

#### Scenario: ECG con las 12 derivaciones completas
- GIVEN un PDF de ECG con los 4 pulsos de calibración y los 12 trazos vectoriales presentes
- WHEN se ejecuta la extracción de señal
- THEN el sistema produce 12 arreglos de 1238 muestras y 1 arreglo de 5000 muestras a 500 Hz
- AND ningún valor de la señal proviene de texto extraído del PDF

#### Scenario: Página rotada 90°
- GIVEN un PDF de ECG cuya página está rotada 90°
- WHEN se calcula el eje temporal de un trazo
- THEN el sistema usa la altura del rectángulo sin rotar como base del tiempo
- AND el resultado coincide con la escala impresa de 25 mm/s

### Requirement: Calibración por pulsos de referencia
El sistema MUST calibrar la señal a mV usando los 4 pulsos de calibración (60 muestras cada
uno) y la escala impresa de 10 mm/mV, MUST validar que los trazos sean negros (0,0,0) con
ancho aproximado 0,43, y MUST NOT calibrar contra ningún otro elemento gráfico de la página.

#### Scenario: Calibración correcta contra el oráculo sintético
- GIVEN un ECG sintético generado con trazos conocidos (oráculo)
- WHEN se extrae y calibra la señal
- THEN el error contra el oráculo es menor o igual a 0,01 mV en cada derivación

### Requirement: Validación geométrica del layout con degradación explícita
El sistema MUST validar que el layout medido (columnas, offsets, conteo de puntos, color y
ancho de trazo) coincida con el layout esperado antes de aceptar la señal como válida.
Cuando la validación falla, el sistema MUST publicar el estudio con `ecg.senal` incluido en
`campos_no_extraidos` y MUST NOT enviarlo a cuarentena por ese motivo.

#### Scenario: Layout que no valida
- GIVEN un PDF de ECG cuyos trazos no coinciden con el layout geométrico esperado
- WHEN se ejecuta la extracción de señal
- THEN el estudio se publica con `ecg.senal` en `campos_no_extraidos`
- AND el estudio NO pasa a cuarentena por esta causa

### Requirement: Aislamiento de texto respecto de la señal
El sistema MUST NOT mezclar ningún dato de texto del encabezado (nombre, DNI, ID de estudio,
fecha) con el arreglo de señal ni con su metadata de calibración.

#### Scenario: Señal sin texto del encabezado
- GIVEN un ECG procesado con header y señal extraídos
- WHEN se inspecciona la estructura de señal persistida
- THEN no contiene ningún campo de texto del encabezado del documento
