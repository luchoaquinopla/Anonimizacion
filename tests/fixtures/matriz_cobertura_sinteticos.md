# Matriz segura de cobertura de plantillas sintéticas

Esta matriz conserva solamente etiquetas y secciones. Las referencias locales se
inspeccionaron sin copiar, persistir ni registrar sus valores, identificadores ni texto
libre. **Cubierto** significa que la etiqueta aparece en el PDF sintético y está protegida
por la prueba contractual `test_corpus_conserva_campos_y_secciones_contractuales_de_cada_origen`.

## ECG

| Etiqueta o sección | Uso | Estado |
|---|---|---|
| MORTARA/12SL, nombre posicional `~,`, ID y fecha | Detección, PII y reconciliación | Cubierto 1:1 |
| Fecha de nacimiento, edad y sexo posicionales | Extracción de cabecera | Cubierto 1:1 |
| Technician, Test ind y Ordered by | Cabecera técnica y médico derivante | Cubierto 1:1 |
| Vent. rate, PR interval, QRS duration, QT/QTc, P-R-T axes | Métricas textuales extraíbles | Cubierto 1:1 |
| PID / NAME MISMATCH | Aviso tolerado por parser | Cubierto 1:1 |
| 25 mm/s, 10 mm/mV, 40 Hz | Calibración / layout | Cubierto |
| Grilla y trazado | Contrato visual | Cubierto, etiquetado como no clínico |
| Señal cruda o diagnóstico clínico | Fuera del PDF textual | Omitido deliberadamente |

## Laboratorio

| Etiqueta o sección | Uso | Estado |
|---|---|---|
| Apellido y Nombre, DNI, fecha de nacimiento, edad | PII y reconciliación | Cubierto |
| Médico derivante, petición, fecha, hora de extracción, origen | Cabecera y PII de profesional | Cubierto |
| Determinación, resultado, unidades, valores de referencia | Tabla extraíble | Cubierto |
| HEMATOLOGIA, HEMOGRAMA, FORMULA LEUCOCITARIA, HEMOSTASIA, QUÍMICA CLÍNICA | Secciones y subsecciones soportadas por parser | Cubierto 1:1 |
| IONOGRAMA SERICO y fila cualitativa | Evidencia no soportada por parser | Cubierto; provoca cuarentena segura |
| Encabezado y pie repetidos | Documento multipágina | Cubierto |

## Ecocardiograma Doppler

| Etiqueta o sección | Uso | Estado |
|---|---|---|
| Paciente, documento, estudio y fecha | PII y reconciliación | Cubierto |
| Médico solicitante, peso, altura, superficie corporal | Cabecera | Cubierto |
| AO, SEPTUM, AI, P.POSTERIOR, DDVI, VD, DSVI, PULMON, FA y AD | Tabla doble de medidas | Cubierto 1:1 |
| Motilidad segmentaria y aurículas | Bloques de texto libre | Cubierto 1:1 |
| Válvulas aórtica, mitral, pulmonar y tricuspídea | Subsecciones de texto libre | Cubierto 1:1 |
| Aurículas izquierda y derecha | Subsecciones de texto libre | Cubierto 1:1 |
| Pericardio y flujos aórtico, mitral, pulmonar y tricuspídeo | Secciones de texto libre | Cubierto 1:1 |
| Doppler tisular | Marcador de firma verificado contra el documento real | Cubierto 1:1 |
| Flujo pulmonar entre páginas | Continuidad y procedencia | Cubierto 1:1 |
| Conclusiones | Bloque final de texto libre | Cubierto 1:1 |
| Nombre del informante y matrícula estructural | Firma / PII profesional | Cubierto 1:1 |

Nota (tarea "regenerar corpus sintético desde layouts reales"): "ECOCARDIOGRAMA
DOPPLER" -- encabezado que este corpus NUNCA usó -- se retiró de
`deteccion/firmas/eco_doppler.py` por no aparecer en el documento real; el
único fixture que sí lo usaba (`tests/fixtures/v1/documentos.py::texto_eco`,
layout legado) ahora usa los mismos dos marcadores reales de cabecera que
esta matriz ya declaraba ("SERVICIO DE ECOCARDIOGRAFIA" / "ECOGRAFIA DOPPLER
COLOR CARDIACA"). Ver `tests/deteccion/test_centinela_corpus_sintetico.py`
para el test que custodia que no vuelva a aparecer un marcador inventado.

## Omisiones deliberadas

- Valores, nombres, DNIs, matrículas, fechas y texto libre de las referencias reales.
- Logos, marcas y estilos propietarios que no cambian la detección o el parseo.
- Una señal ECG digital o una interpretación clínica: el trazado es una figura sintética y no
  representa una señal ni un resultado médico.
- Variantes no observadas en las referencias autorizadas; deberán incorporarse sólo desde
  muestras anonimizadas aprobadas y con una prueba contractual nueva.
