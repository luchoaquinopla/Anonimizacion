## Exploration: ingesta-pdf-clinicos

### Current State
El repositorio no contiene una aplicacion ni un stack definido; OpenSpec esta inicializado en modo hibrido y no hay ejecutor de pruebas. La muestra conocida incluye tres PDFs clinicos digitales, no cifrados y con texto extraible: laboratorio multipagina con tablas, ecocardiografia con tablas y narrativa, y ECG con metadatos textuales y trazado grafico. Esta evidencia es limitada: no prueba cobertura para todos los emisores ni para PDFs escaneados.

Restriccion no negociable: ningun PDF, texto crudo, PII, archivo temporal ni payload de cola puede persistirse. La extraccion debe ocurrir en memoria, seguida de anonimización, validación residual y persistencia exclusiva de datos permitidos.

### Affected Areas
- `openspec/changes/ingesta-pdf-clinicos/exploration.md` — evidencia, alternativas y recomendacion inicial.
- Futuro servicio de ingesta — clasificacion, extraccion transitoria, anonimización y control de calidad.
- Futuro esquema de datos — contrato canonico anonimizado y trazabilidad sin contenido sensible.

### Approaches
1. **Extractor local en Python con PyMuPDF como motor principal** — extraer por pagina texto, bloques, coordenadas y tablas desde el PDF en memoria; usar plantillas/adaptadores por familia documental para convertir el resultado a un contrato clinico canonico.
   - Pros: PyMuPDF extrae texto y tablas; un unico runtime integra parsing, reglas clinicas, OCR local y validacion. Permite conservar procedencia tecnica sin almacenar contenido crudo. La muestra es digital, por lo que el camino principal no requiere OCR.
   - Cons: el orden de lectura y la deteccion de tablas no son infalibles; requiere pruebas de regresion por plantilla y una cola de revision para extracciones ambiguas que no conserve PII.
   - Effort: Medio.

2. **Pipeline de IA documental/servicio cloud** — enviar los documentos a un proveedor de OCR, layout o modelos generativos para estructurarlos.
   - Pros: puede acelerar la exploracion de layouts variables y documentos escaneados.
   - Cons: contradice por defecto la restriccion de no sacar ni persistir datos personales fuera del perimetro; introduce dependencia, costos, versionado opaco y riesgos regulatorios. No es aceptable sin evaluacion legal, DPA y controles de residencia de datos.
   - Effort: Medio/Alto.

3. **Extractor generico sin adaptadores de tipo documental** — convertir todo a texto plano y aplicar reglas universales.
   - Pros: inicio rapido y menor codigo inicial.
   - Cons: no preserva suficientemente semantica ni celdas de tablas; no permite demostrar completitud para los tres formatos. Es particularmente fragil ante orden de lectura, unidades y campos homonimos.
   - Effort: Bajo inicialmente; Alto por retrabajo.

### Recommendation
Adoptar **Python local** para workers aislados, con **PyMuPDF** como extractor primario y un diseño basado en adaptadores versionados por familia documental. PyMuPDF soporta extraccion de texto, bloques y tablas; debe configurarse y evaluarse contra una bateria representativa, no asumirse exactitud. Para tablas que no cumplan los umbrales de calidad, usar una estrategia secundaria local (por ejemplo, pdfplumber) solo dentro del mismo proceso y en memoria. Para futuros escaneados, incorporar OCR local como ruta excepcional y medirlo por separado.

El contrato canonico debe separar: `document_type`, `schema_version`, `extraction_version`, `source_locator` (pagina, bloque/celda y confianza, sin texto), `observations` clinicas normalizadas (codigo/nombre estandar, valor, unidad, rango cuando exista, estado de calidad) y `quality` (cobertura, ambiguedades, reglas ejecutadas). No debe incluir texto fuente, imagenes, identificadores ni fechas que permitan reidentificacion. La asociacion estable entre documentos solo se permite si se aprueba explicitamente como seudonimizacion; no es anonimización.

Flujo propuesto: PDF recibido en memoria -> clasificador de tipo -> extractor/adaptador -> detector de PII/PHI y reglas locales -> eliminacion o generalizacion -> validador residual independiente -> validador de calidad y completitud -> persistencia del JSON permitido. La cola solo transporta una referencia efimera de ejecucion y controles tecnicos no identificantes; el worker no escribe archivos temporales, logs con contenido ni resultados crudos. Los fallos persisten solo codigos, version y metricas agregadas.

Para PII, Presidio puede aportar reconocimiento y operadores de redaccion/reemplazo, pero no debe considerarse cobertura clinica completa sin reconocedores locales para formatos argentinos, vocabulario medico y cada plantilla. La validacion residual debe ser independiente del detector primario y bloquear la persistencia ante hallazgos o calidad insuficiente.

El ECG requiere una decision de producto: los metadatos y medidas textuales se pueden extraer como los otros documentos; el trazado dibujado en un PDF no es una fuente fiable de señal para ML. Si el modelo necesita la onda, se debe exigir una fuente nativa validada (DICOM, XML o WFDB) y no reconstruirla desde el PDF.

### Risks
- La completitud no puede afirmarse con tres muestras: se necesita un corpus de evaluacion representativo y anotado dentro de un entorno controlado, con metricas por campo, tabla, pagina y tipo documental.
- Campos clinicos, unidades, valores de referencia y fechas pueden ser ambiguos o estar visualmente presentes en un orden de extraccion distinto; persistirlos sin calidad/procedencia puede contaminar el dataset de ML.
- El detector de PII puede omitir identificadores locales o PII incrustada en narrativa; una sola pasada es insuficiente.
- La ausencia de persistencia de originales limita reprocesos y auditoria de contenido: definir una operacion aprobada para reingesta desde la fuente autorizada, sin crear una copia en este sistema.
- OCR, si aparece en el alcance, puede degradar nombres, numeros y unidades; debe incorporar umbrales, cuarentena no persistente y medicion separada.

### Ready for Proposal
Sí. La propuesta debe acotar un primer spike local y medible: definir el contrato canonico, los umbrales de completitud y privacidad, adaptadores para las tres familias observadas y una estrategia de pruebas con corpus controlado. Antes de implementar, debe aclarar si el modelo usa solo medidas/metadata de ECG o necesita la señal nativa.

### Referencias tecnicas
- PyMuPDF: extraccion de texto, bloques y tablas: https://pymupdf.readthedocs.io/en/latest/the-basics.html
- PyMuPDF: limites de orden de lectura y layout: https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- Presidio: deteccion y anonimización extensible: https://microsoft.github.io/presidio/text_anonymization/
