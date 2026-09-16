# Extracción de Señal de ECG — Delta

## MODIFIED Requirements

### Requirement: Extracción vectorial de las 12 derivaciones + tira de ritmo
El sistema MUST extraer, usando sólo `get_drawings()` (nunca texto ni OCR), las 12
derivaciones estándar (1238 muestras cada una) más la tira de ritmo V1 (5000 muestras),
a 500 Hz, distribuidas en 4 columnas de 3 derivaciones con offsets de tiempo 0/2,5/5/7,5 s.
El sistema MUST resolver el eje temporal a partir de la altura del rectángulo de trazo sin
rotar, dado que la página se exporta rotada 90°.

El sistema MUST derivar el SENTIDO en que avanza el tiempo (Y creciente o decreciente) de
la posición de los pulsos de calibración, que siempre marcan el inicio del registro — el
tiempo avanza alejándose de ellos. El sistema MUST NOT asumir un sentido fijo por defecto.
Si los pulsos no quedan claramente más allá de un extremo de las derivaciones, el sistema
MUST tratar la dirección como ambigua y no extraer la señal.

El sistema MUST usar esa dirección para: (a) ordenar las 4 columnas por su distancia real
a los pulsos (la más cercana es la columna del offset 0), (b) orientar cada trazo de
derivación en el tiempo, y (c) orientar la tira de ritmo.

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

#### Scenario: Dirección del tiempo derivada de los pulsos, no asumida
- GIVEN un PDF de ECG cuyos pulsos de calibración quedan más allá del extremo de Y máxima
  de todas las derivaciones y de la tira
- WHEN se ejecuta la extracción de señal
- THEN el sistema resuelve el tiempo como creciente hacia Y decreciente
- AND la columna más cercana a los pulsos se asigna al offset de tiempo 0

#### Scenario: Dirección del tiempo ambigua
- GIVEN un PDF de ECG cuyos pulsos de calibración no quedan claramente más allá de ningún
  extremo de Y de las derivaciones
- WHEN se ejecuta la extracción de señal
- THEN el sistema no extrae la señal

### Requirement: Calibración por pulsos de referencia
El sistema MUST calibrar la señal a mV usando los 4 pulsos de calibración (60 muestras cada
uno) y la escala impresa de 10 mm/mV, MUST validar que los trazos sean negros (0,0,0) con
ancho aproximado 0,43, y MUST NOT calibrar contra ningún otro elemento gráfico de la página.

#### Scenario: Calibración correcta contra el oráculo sintético
- GIVEN un ECG sintético generado con trazos conocidos (oráculo)
- WHEN se extrae y calibra la señal
- THEN el error contra el oráculo es menor o igual a 0,01 mV en cada derivación

### Requirement: Validación geométrica y fisiológica del layout con degradación explícita
El sistema MUST validar que el layout medido (columnas, offsets, conteo de puntos, color y
ancho de trazo) coincida con el layout esperado antes de aceptar la señal como válida.

Adicionalmente, el sistema MUST validar que la señal calibrada cumpla las identidades
fisiológicas de Einthoven (`II = I + III`, sobre la columna de derivaciones de miembros) y
de Goldberger (`aVR + aVL + aVF = 0`, sobre la columna de derivaciones aumentadas), y que la
derivación V1 de la grilla (descartada en favor de la tira de ritmo) correlacione con el
segmento equivalente de esa tira. El sistema MUST descartar la señal completa (no una
derivación parcial) si cualquiera de estas validaciones falla, incluso si cada banda de
amplitud calibró individualmente sin error.

Cuando cualquier validación falla, el sistema MUST publicar el estudio con `ecg.senal`
incluido en `campos_no_extraidos` y MUST NOT enviarlo a cuarentena por ese motivo.

#### Scenario: Layout que no valida
- GIVEN un PDF de ECG cuyos trazos no coinciden con el layout geométrico esperado
- WHEN se ejecuta la extracción de señal
- THEN el estudio se publica con `ecg.senal` en `campos_no_extraidos`
- AND el estudio NO pasa a cuarentena por esta causa

#### Scenario: Columnas o filas cruzadas pese a calibrar correctamente
- GIVEN un PDF de ECG donde cada banda de amplitud calibra sin error, pero el contenido de
  dos columnas o dos filas está intercambiado entre sí
- WHEN se ejecuta la extracción de señal
- THEN la validación de Einthoven o de Goldberger falla
- AND el sistema no extrae la señal

### Requirement: Aislamiento de texto respecto de la señal
El sistema MUST NOT mezclar ningún dato de texto del encabezado (nombre, DNI, ID de estudio,
fecha) con el arreglo de señal ni con su metadata de calibración.

#### Scenario: Señal sin texto del encabezado
- GIVEN un ECG procesado con header y señal extraídos
- WHEN se inspecciona la estructura de señal persistida
- THEN no contiene ningún campo de texto del encabezado del documento
