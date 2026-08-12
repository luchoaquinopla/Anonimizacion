# Propuesta: Ingesta local de PDFs clínicos con carga manual

## Intención

Habilitar una primera entrega local para evaluar la ingesta de muestras clínicas mediante una interfaz de navegador: la persona usuaria arrastra varios PDFs y recibe, sólo cuando termina el lote completo, un acuse técnico seguro. Cada PDF se procesa de forma síncrona y exclusivamente en memoria; el flujo preserva las barreras de anonimización y validación, pero no expone datos clínicos anonimizados en esta interfaz ni conserva resultados.

La entrega separa la entrada del caso de uso mediante un puerto de entrada. Así, futuros adaptadores autorizados podrán invocar la misma extracción y validación anonimizada sin acoplar el dominio a la carga manual actual.

## Alcance

### Incluye

- Adaptador de carga manual local, basado en navegador, que acepta el arrastre de múltiples PDFs de muestra.
- Procesamiento síncrono, en memoria y por cada PDF del lote antes de emitir la respuesta.
- Ejecución del caso de uso de clasificación, extracción por familia documental, anonimización, validación residual independiente y validación de calidad/completitud.
- Un único acuse de lote al finalizar todos los archivos, con cantidades recibidas y procesadas, y códigos técnicos seguros por archivo. Los códigos no contendrán nombres, texto, valores clínicos, identificadores ni otra información que permita reidentificar.
- Un puerto de entrada para el caso de uso de ingesta, implementado por el adaptador de carga manual local, que mantenga desacoplada la extracción y validación del origen de los PDFs.
- Adaptadores versionados para laboratorio, ecocardiografía y ECG; para ECG, sólo metadatos y medidas textuales, nunca la señal del trazado.
- Corpus controlado/anotado, inventario versionado de campos esperados y métricas por familia documental para medir extracción, privacidad y regresión, sin incorporar las muestras ni su contenido al sistema.

### Excluye

- Exponer la interfaz en red, autenticación, API pública, selector de carpetas, *watcher*, integración hospitalaria, colas o *broker*.
- Elegir, diseñar o comprometer un origen futuro, proveedor de autenticación, *framework*, almacenamiento o mecanismo de transporte.
- Persistir PDFs, texto extraído, PII/PHI, datos clínicos anonimizados, resultados, archivos temporales, registros con contenido o *payloads* de cola. Al terminar cada archivo, sus datos transitorios se descartan; al finalizar el lote, sólo se devuelve el acuse en la respuesta.
- Mostrar en la UI datos clínicos anonimizados, observaciones, *features*, contenido extraído o diagnósticos.
- Definir *target*, entrenar modelos, generar o persistir *features*, o garantizar cobertura fuera del corpus evaluado.
- Extraer la señal del trazado ECG desde un PDF o realizar vinculación longitudinal.

## Capacidades

### Nuevas capacidades

- `carga-manual-local`: recibe un lote de PDFs arrastrados en un navegador local y entrega un acuse técnico seguro al concluirlo.
- `ingesta-clinica-anonimizada`: caso de uso invocable por un puerto de entrada; procesa en memoria, aplica controles de privacidad y descarta toda salida transitoria.
- `validacion-privacidad-y-calidad`: comprueba PII/PHI residual, completitud y calidad antes de considerar procesado un archivo, sin conservar su contenido ni resultado clínico.
- `calidad-de-extraccion`: mide la cobertura del corpus de evaluación por familia documental sin incorporar contenido sensible en el producto.

### Capacidades modificadas

- Ninguna.

## Enfoque

El navegador local entrega cada PDF del lote al adaptador de carga manual. Éste invoca el puerto de entrada de ingesta y espera su finalización síncrona en memoria. El caso de uso clasifica el documento, aplica el extractor/adaptador de su familia, anonimiza y ejecuta validación residual independiente junto con controles de calidad y completitud. La salida clínica transitoria no cruza el límite de la interfaz y se descarta, tanto ante éxito como ante error. Una vez tratados todos los archivos, el adaptador compone el acuse de lote con contadores y códigos técnicos seguros por archivo.

El puerto representa la entrada de PDFs al caso de uso, no un compromiso con protocolos ni fuentes futuras. Un adaptador posterior —por ejemplo, de carpeta, API autenticada, sistema hospitalario o cola— podrá suministrar el mismo caso de uso sólo tras una decisión de producto, privacidad y operación independiente. No forma parte de esta entrega elegirlo ni implementarlo.

La UI y el proceso se ejecutarán localmente y no se expondrán por red. No se crearán archivos temporales ni persistencia de ningún tipo; tampoco se registrará contenido de los documentos, texto extraído, PII/PHI, datos anonimizados ni resultados. La observabilidad, si se aprobara posteriormente, deberá limitarse a códigos técnicos no identificantes y no forma parte de esta propuesta.

## Áreas afectadas

| Área | Impacto | Descripción |
| --- | --- | --- |
| `openspec/changes/ingesta-pdf-clinicos/proposal.md` | Modificada | Define la primera forma de entrega aprobada y sus límites. |
| Futuro adaptador local de navegador | Nueva | Carga manual múltiple y acuse técnico de lote. |
| Futuro caso de uso de ingesta y puerto de entrada | Nuevo | Límite estable entre los adaptadores de origen y extracción/validación. |
| Futuro dominio de extracción y validación | Nuevo | Procesamiento transitorio por familia documental, anonimización y controles de calidad. |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
| --- | --- | --- |
| PII/PHI residual durante la extracción | Media | Procesar sólo en memoria, aplicar anonimización y validación residual independiente, y no exponer ni persistir salidas. |
| El usuario interpreta un código técnico como resultado clínico | Media | Limitar el acuse a contadores y códigos técnicos seguros; no mostrar observaciones, valores ni diagnósticos. |
| Variación de formatos u omisiones clínicas | Alta | Adaptadores versionados, corpus anotado, umbrales acordados y métricas de regresión. |
| El navegador local o su configuración se expone accidentalmente en red | Media | Establecer y verificar explícitamente la ejecución sólo local y sin exposición de red. |
| La falta de persistencia impide reintentos o auditoría de contenido | Alta | Solicitar una nueva carga desde la fuente autorizada; cualquier retención requerirá una propuesta y aprobación separadas. |

## Plan de reversión

Deshabilitar el adaptador de carga manual local y retirar su acceso local. Como no se persisten PDFs, texto, PII/PHI, resultados ni temporales, la reversión no requiere purga ni migración de datos. El origen autorizado conserva, fuera de este sistema, la posibilidad de volver a proporcionar una muestra si corresponde.

## Dependencias

- Corpus autorizado y anotado, inventario versionado de campos esperados y criterios acordados de calidad y privacidad.
- Definición de códigos técnicos seguros que no revelen contenido ni identidad.
- Verificación operativa de que la UI y el proceso se ejecutan exclusivamente en el equipo local y sin exposición de red.

## Criterios de éxito

- [ ] Una persona puede arrastrar múltiples PDFs de muestra en una UI local y recibe un único acuse después de que termina el procesamiento síncrono de todo el lote.
- [ ] El acuse informa cantidades recibidas/procesadas y sólo códigos técnicos seguros por archivo; no expone datos clínicos anonimizados, texto, PII/PHI ni resultados detallados.
- [ ] No se persisten PDFs, texto crudo, PII/PHI, datos anonimizados, resultados, temporales, registros con contenido, *payloads* de cola ni datos intermedios.
- [ ] La carga manual invoca el caso de uso mediante un puerto de entrada, sin acoplar extracción y validación a este origen ni seleccionar adaptadores futuros.
- [ ] Cada archivo completa anonimización, validación residual y controles de calidad/completitud en memoria antes de descartarse.
- [ ] El corpus informa cobertura, exactitud de valor/unidad, omisiones, rechazos y PII residual; los umbrales se acuerdan antes de cualquier uso productivo.
