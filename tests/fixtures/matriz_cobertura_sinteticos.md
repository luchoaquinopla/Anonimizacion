# Matriz segura de cobertura de plantillas sintéticas

Esta matriz conserva solamente etiquetas y secciones. Las referencias locales se
inspeccionaron sin copiar, persistir ni registrar sus valores, identificadores ni texto
libre. **Cubierto** significa que la etiqueta aparece en el PDF sintético y está protegida
por la prueba contractual `test_corpus_conserva_campos_y_secciones_contractuales_de_cada_origen`.

## ECG

| Etiqueta o sección | Uso | Estado |
|---|---|---|
| 12SL, PID, paciente y fecha | Detección, PII y reconciliación | Cubierto |
| Age, Sex | Extracción de cabecera | Cubierto |
| Technician | PII de profesional | Cubierto |
| Vent. rate, PR interval, QRS duration, QT/QTc, P-R-T axes | Métricas extraíbles | Cubierto |
| PID / NAME MISMATCH | Aviso tolerado por parser | Cubierto |
| 25 mm/s, 10 mm/mV, 40 Hz | Calibración / layout | Cubierto |
| Grilla y trazado | Contrato visual | Cubierto, etiquetado como no clínico |
| Señal cruda o diagnóstico clínico | Fuera del PDF textual | Omitido deliberadamente |

## Laboratorio

| Etiqueta o sección | Uso | Estado |
|---|---|---|
| Apellido y Nombre, DNI, fecha de nacimiento, edad | PII y reconciliación | Cubierto |
| Médico derivante, petición, fecha, hora de extracción, origen | Cabecera y PII de profesional | Cubierto |
| Determinación, resultado, unidades, valores de referencia | Tabla extraíble | Cubierto |
| HEMATOLOGIA, HEMOGRAMA, FORMULA LEUCOCITARIA, HEMOSTASIA, QUIMICA CLINICA | Secciones y subsecciones soportadas por parser | Cubierto 1:1 |
| IONOGRAMA SERICO y fila cualitativa | Evidencia no soportada por parser | Cubierto; provoca cuarentena segura |
| Encabezado y pie repetidos | Documento multipágina | Cubierto |

## Ecocardiograma Doppler

| Etiqueta o sección | Uso | Estado |
|---|---|---|
| Paciente, documento, estudio y fecha | PII y reconciliación | Cubierto |
| Médico solicitante, peso, altura, superficie corporal | Cabecera | Cubierto |
| AO, AI, DDVI, DSVI, FA, Septum, P. Posterior | Tabla de medidas | Cubierto |
| Motilidad segmentaria | Bloque de texto libre | Cubierto |
| Válvulas mitral, aórtica, tricúspidea y pulmonar | Secciones de texto libre | Cubierto |
| Pericardio, Doppler, conclusiones | Secciones de texto libre | Cubierto |
| Médico informante y matrícula | Firma / PII profesional | Cubierto |

## Omisiones deliberadas

- Valores, nombres, DNIs, matrículas, fechas y texto libre de las referencias reales.
- Logos, marcas y estilos propietarios que no cambian la detección o el parseo.
- Una señal ECG digital o una interpretación clínica: el trazado es una figura sintética y no
  representa una señal ni un resultado médico.
- Variantes no observadas en las referencias autorizadas; deberán incorporarse sólo desde
  muestras anonimizadas aprobadas y con una prueba contractual nueva.
