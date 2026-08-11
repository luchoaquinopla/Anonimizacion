# Propuesta: Ingesta de PDFs clínicos anonimizada

## Intención
Extraer la máxima información clínica de PDFs heterogéneos y conservar observaciones anonimizadas y trazables. Aún no se define una predicción: cada valor será una *feature* potencial para datasets ML.

## Alcance

### Incluye
- Pipeline local en memoria: clasificación, extracción por tipo documental, anonimización, validación residual y control de completitud antes de persistir.
- Adaptadores versionados para laboratorio, ecocardiografía y ECG; del ECG sólo metadatos y medidas textuales.
- Fuente SQL relacional: tipo, código/nombre, valor, unidad, rango, procedencia técnica, versión y calidad.
- JSON anonimizado de intercambio, sin reemplazar el esquema relacional; tablas de *features* derivadas y versionadas.
- Corpus controlado/anotado, inventario versionado de campos esperados, métricas por tipo y regresión.

### Excluye
- Definir el *target*, entrenar modelos o garantizar cobertura fuera del corpus evaluado.
- Persistir PDFs, texto crudo, PII/PHI, temporales, payloads de cola o logs con contenido.
- Extraer la señal del trazado ECG desde el PDF.
- Vinculación longitudinal: exige seudonimización aprobada, no anonimización.

## Capacidades

### Nuevas capacidades
- `ingesta-clinica-anonimizada`: procesa en memoria y bloquea persistencia indebida.
- `observaciones-clinicas`: normaliza observaciones y calidad.
- `calidad-de-extraccion`: mide cobertura por familia.
- `datasets-ml-derivados`: genera *features* versionadas desde observaciones aprobadas.

### Capacidades modificadas
- Ninguna.

## Enfoque
Workers locales en Python, PyMuPDF como extractor principal y adaptadores por familia documental. Una alternativa local para tablas se usa sólo si no alcanza el umbral de calidad. El contenido permanece en memoria hasta superar anonimización y validación residual independiente. Se persisten tablas SQL normalizadas y JSONB anonimizado trazable, nunca JSON crudo como único esquema. OCR local será una ruta futura medida por separado.

## Áreas afectadas

| Área | Impacto | Descripción |
|---|---|---|
| `openspec/changes/ingesta-pdf-clinicos/` | Modificada | Artefactos. |
| Futuro servicio de ingesta | Nueva | Workers, adaptadores y validadores. |
| Futuro esquema SQL | Nuevo | Observaciones y *features* derivadas. |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| Omisión clínica | Alta | Inventario, corpus anotado, umbrales y bloqueo por calidad. |
| PII residual | Media | Dos validadores; bloquear persistencia. |
| Variación de formato | Alta | Adaptadores versionados y regresión. |

## Plan de reversión
Deshabilitar la versión defectuosa y detener la persistencia; reingestar desde la fuente autorizada.

## Dependencias
- Corpus autorizado, inventario de campos y criterios de calidad/privacidad.
- Acordar stack, almacenamiento y controles operativos.

## Criterios de éxito
- [ ] No persiste contenido personal ni crudo.
- [ ] Cada campo esperado concluye con un estado auditable; no hay omisiones silenciosas.
- [ ] El corpus informa cobertura, exactitud de valor/unidad, omisiones, rechazos y PII residual; los umbrales se acuerdan antes de producción.
- [ ] Sólo observaciones verificadas alimentan *features* derivadas sin alterar la fuente de verdad.


