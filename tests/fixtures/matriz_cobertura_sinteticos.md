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
  representa una señal ni un resultado médico (además, la grilla/trazado vectorial del ECG se
  retiró en la tarea "invertir la dirección del corpus sintético": era una figura decorativa que
  ningún test verifica, y su costo de dibujado dominaba el tiempo de generación -- ver esa tarea
  para las mediciones).
- Variantes no observadas en las referencias autorizadas; deberán incorporarse sólo desde
  muestras anonimizadas aprobadas y con una prueba contractual nueva.
- (Sólo ecocardiograma) El nombre completo de la institución y la línea de dirección/teléfono
  del pie: ninguno de los dos tiene un prefijo genérico seguro en
  `parseo/eco_doppler.py::_PREFIJOS_BOILERPLATE` sin inventar o filtrar un dato institucional
  real -- ver `plantilla_documento.py::_recuperar_boilerplate_eco`.

## Tarea "invertir la dirección del corpus sintético"

`tests/fixtures/pdf_sintetico.py` dejó de reconstruir cada tipo de documento a
mano: ahora dibuja el contenido de `tests/fixtures/plantilla_documento.py`,
que toma como MOLDE el fixture parseable real versionado
(`tests/fixtures/parseables/{tipo}-01.txt`) y sólo sustituye identidad
(nombre, DNI, fechas, números de petición/estudio/ECG) por documento. El
centinela `tests/fixtures/test_cobertura_plantillas.py` mide, contra el PDF
real que `generar_corpus_clinico` termina escribiendo, qué porcentaje del
vocabulario estructural de la plantilla (excluyendo identidad y el
boilerplate recuperado del eco) reproduce -- con un piso fijo del 95% escrito
en el test. Medido contra esta implementación: ECG, laboratorio y
ecocardiograma reproducen el 100% del vocabulario exigido.

Cobertura del vocabulario de los documentos REALES (medida por el pedido de
esta tarea, antes de esta tarea → generador anterior, hoy → plantilla real):
laboratorio 38% → ~100%, ecocardiograma 42% → ~100%, ecg 62% → ~100%.

Dos hallazgos de parser reales, encontrados al enfrentar el generador contra
el layout completo (no del corpus sintético en sí -- se confirmaron leyendo
el PDF real bajo `D:\ejemplos_pdf\`, sin copiar su contenido a ningún
archivo):

- `parseo/eco_doppler.py::es_boilerplate_eco` comparaba contra el prefijo
  `"informe no valido"` (sin tilde) usando sólo `casefold()`, que no saca
  acentos -- la línea real trae "Informe no válido..." (con tilde) y nunca
  matcheaba, en NINGÚN documento real, no sólo en el sintético. Fix: le saca
  los acentos a la línea antes de comparar.
- `parseo/eco_doppler.py::_CAMPOS_HEADER["medico_solicitante"]` nunca podía
  protegerse en `esqueleto.py` (su regex arranca con una clase de caracteres
  justo después de la primera letra, `M[eé]dico`, y el extractor de prefijo
  literal de `esqueleto.py` se detiene ahí) -- la plantilla real la trae
  enmascarada por forma. `plantilla_documento.py` la relabeliza a la forma
  canónica no identificatoria ("Medico Solicitante:") porque, sin ella
  reconocible, la sección "FLUJO PULMONAR" (que continúa entre páginas) se
  contamina con el header repetido de la página siguiente y la reconciliación
  la rechaza con `evidencia_ausente`.

"PID / NAME MISMATCH" (ECG) y "DIAGNOSTICO POR IMAGENES" (eco) NO aparecen en
las plantillas reales usadas (no es que se enmascararan: esas muestras en
particular no traen esa alerta de equipo ni ese sello de especialidad) pero
sí son constantes que un parser real ya sabe reconocer
(`parseo/ecg_mortara.py::_ADVERTENCIA_PID_MISMATCH`,
`parseo/eco_doppler.py::_TEXTO_FIRMA_EXCLUIDO`) -- se agregan como líneas
sintéticas explícitas, igual que el pie "DOCUMENTO SINTETICO - SOLO
PRUEBAS", para seguir calibrando esas dos ramas.

## Tarea "usar la plantilla completa"

El "100%" de vocabulario de la sección anterior era real pero ENGAÑOSO como
prueba de que "la plantilla se usa completa": `laboratorio_general.py` y
`eco_doppler.py` dibujaban el orden GEOMÉTRICO de la plantilla (`sort=True`,
el que fusiona varias columnas en una sola línea de texto) como UNA sola
cadena por fila. Medido con PyMuPDF contra el PDF que `generar_corpus_clinico`
terminaba escribiendo: laboratorio reproducía 91 de las 226 líneas reales
(orden de dibujado, sin `sort`), ecocardiograma 68 de 173, ECG 57 de 52 (ya
sobre el 100%, sin cambios). El vocabulario (conjunto de PALABRAS) seguía
dando ~100% porque NINGUNA palabra se perdía al fusionar columnas en menos
líneas -- pero las dos representaciones que expone
`extraccion/texto_pymupdf.py` (`paginas` orden de dibujado / `paginas_ordenadas`
orden geométrico) terminaban siendo casi idénticas entre sí, así que ningún
test ejercitaba la razón por la que existen las dos (ver su docstring: contra
el ECG real, 3/4 marcadores en orden de dibujado vs 1/4 en geométrico).

Fix: `plantilla_documento.py` tokeniza cada fila geométrica en sus columnas
(`_tokenizar_fila` -- separador de 2+ espacios más una partición fina de
"Etiqueta: valor" y "número unidad" unidos por un solo espacio) y dibuja cada
token como un `insert_text` INDEPENDIENTE (`pdf_sintetico._dibujar_fragmentos_plantilla`),
posicionado en su fila/columna real pero EMITIDO (orden de llamada) según la
sección "orden de dibujado" de la plantilla para los tokens que son únicos en
la página (`_fragmentos_en_orden_de_dibujado`) -- ver el reporte completo de
la tarea para las cifras de fidelidad de orden logradas (altas para dibujado,
más bajas y reportadas sin forzar para geométrico) y dos hallazgos de
posicionamiento (intercalado de caracteres por subestimar el ancho real a
fontsize chico; reconstrucción de "valor unidad" como dos columnas en vez de
una por un espaciado entre columnas demasiado ancho).

Centinelas nuevos:
- `tests/fixtures/test_fidelidad_lineas_plantillas.py` -- piso fijo de
  cantidad de líneas no vacías (orden de dibujado) por tipo, ≥95% de la
  plantilla real, con test dedicado que prueba que detecta la regresión
  concreta que motivó esta tarea.
- `tests/fixtures/test_fidelidad_orden_plantillas.py` -- fidelidad de orden
  (subsecuencia común más larga) contra ambas representaciones, con pisos
  fijos medidos, priorizando dibujado sobre geométrico.

Costo del banco de 1.000 documentos (mismo oráculo: 972 aprobados / 26 en
cuarentena, sin cambios): tiempo total subió de 81.4s (47.8s preparación +
29.4s procesamiento + 4.2s verificación) a 140.5s (106.0s preparación + 30.3s
procesamiento + 4.2s verificación) -- el aumento es casi todo en preparación
(más `insert_text` por documento, uno por columna en vez de uno por fila), tal
como se esperaba al dibujar la plantilla completa; no se recortó la plantilla
para evitarlo.
