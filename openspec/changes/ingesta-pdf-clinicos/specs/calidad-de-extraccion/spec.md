# Especificación: Calidad de extracción

## Propósito

Medir con un corpus controlado la cobertura y confiabilidad de los adaptadores por familia documental, sin incorporar muestras ni contenido sensible al producto.

En esta especificación, DEBE corresponde a MUST (obligatorio) y NO DEBE corresponde a MUST NOT (prohibido) según RFC 2119.

## Requisitos

### Requisito: Corpus, inventario y métricas por familia

Cada adaptador versionado de laboratorio, ecocardiografía y ECG DEBE evaluarse contra un corpus autorizado y anotado y su inventario versionado de campos esperados. La evaluación DEBE informar, por familia y versión, cobertura, exactitud de valor y unidad, omisiones, rechazos y PII/PHI residual. Para ECG, la evaluación DEBE limitarse a metadatos y medidas textuales y NO DEBE extraer ni evaluar la señal del trazado.

#### Escenario: Evaluación de un adaptador

- DADO un corpus autorizado con resultados esperados para una familia documental
- CUANDO se evalúa una versión de su adaptador
- ENTONCES la evaluación DEBE producir las métricas requeridas por familia y versión
- Y NO DEBE incorporar los PDFs, su texto ni valores clínicos al producto

#### Escenario: Documento ECG

- DADO un PDF de ECG en el corpus controlado
- CUANDO se evalúa el adaptador correspondiente
- ENTONCES DEBE considerar sólo metadatos y medidas textuales admitidas
- Y NO DEBE extraer la señal del trazado

### Requisito: Umbrales y regresión

Los umbrales numéricos de calidad y privacidad DEBEN acordarse a partir del corpus antes de cualquier uso productivo. Una versión sin umbrales aprobados o que incumpla alguno NO DEBE considerarse apta.

#### Escenario: Umbral ausente o incumplido

- DADA una versión sin umbral aprobado o con una métrica inferior al umbral aplicable
- CUANDO se evalúa su aptitud
- ENTONCES el sistema DEBE declararla no apta
- Y NO DEBE habilitarla para uso productivo

### Requisito: Evaluación sin retención sensible

El corpus y su contenido DEBEN permanecer fuera del producto. La evaluación NO DEBE persistir en el producto PDFs, texto, PII/PHI, valores clínicos, resultados por muestra ni datos intermedios; sus salidas permitidas DEBEN limitarse a métricas técnicas agregadas no identificantes.

#### Escenario: Final de una evaluación

- DADO que una ejecución de evaluación procesó muestras autorizadas
- CUANDO finaliza
- ENTONCES el producto NO DEBE conservar las muestras, su contenido ni resultados por muestra
- Y sólo DEBE comunicar métricas agregadas que no permitan reconstruir ni identificar un documento

#### Escenario: Métrica con riesgo de identificación

- DADO un desglose que permitiría inferir contenido o identidad de una muestra
- CUANDO se prepara el informe de evaluación
- ENTONCES el sistema DEBE omitir o agregar ese desglose hasta que sea no identificante
