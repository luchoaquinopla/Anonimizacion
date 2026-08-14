# Extracción de Texto de PDF — Especificación

## Purpose

Extraer texto nativo y su posición desde los 3 layouts de PDF conocidos (ECG Mortara,
laboratorio, ecocardiograma) como entrada para las etapas posteriores del pipeline.

## Requirements

### Requirement: Extracción de texto nativo
El sistema MUST extraer el texto nativo y sus coordenadas de página usando PyMuPDF para
cualquier PDF de los 3 layouts soportados, sin usar OCR (los 3 tipos son texto nativo).

#### Scenario: Extracción de laboratorio multi-página
- GIVEN un PDF de laboratorio con header repetido en cada página
- WHEN se ejecuta la extracción
- THEN el sistema produce el texto completo de todas las páginas con su posición
- AND no se pierde ningún bloque de texto de ninguna página

#### Scenario: Extracción de ECG con trazado rasterizado
- GIVEN un PDF de ECG cuyo trazado es una imagen rasterizada
- WHEN se ejecuta la extracción
- THEN el sistema extrae el texto del header y las medidas numéricas
- AND NO intenta interpretar la imagen del trazado como texto

### Requirement: Fallo explícito por documento corrupto
El sistema MUST fallar de forma explícita y aislada para un documento cuyo texto no puede
extraerse (PDF corrupto o vacío de texto), sin detener el procesamiento del resto del lote.

#### Scenario: PDF corrupto en un lote
- GIVEN un lote de 10 PDFs donde 1 está corrupto
- WHEN se ejecuta la extracción sobre el lote
- THEN el documento corrupto se marca con estado de fallo explícito
- AND los otros 9 documentos se procesan normalmente
