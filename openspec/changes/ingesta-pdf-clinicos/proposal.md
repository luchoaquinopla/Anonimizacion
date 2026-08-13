# Propuesta: Ingesta local de PDFs clínicos de laboratorio

## Decisión y resultado esperado

La primera entrega implementable será una UI de navegador **local** para arrastrar PDFs de laboratorio. Procesará cada archivo del lote de manera síncrona y sólo en memoria; al completar el lote devolverá un acuse técnico seguro. No persistirá ni mostrará contenido clínico, texto extraído, PII/PHI, observaciones ni resultados detallados.

La entrega se realizará como una cadena de PRs revisables, de aproximadamente 400 líneas modificadas cada uno. La UI y el procesamiento de laboratorio se consideran completos únicamente al integrar los PRs iniciales de esa cadena.

## Alcance del primer incremento

### Incluye

- UI local de navegador para arrastrar múltiples PDFs de laboratorio.
- Procesamiento en memoria, síncrono y archivo por archivo dentro de un lote.
- Clasificación limitada a la familia de laboratorio, extracción transitoria, anonimización y validación residual independiente de PII/PHI.
- Controles de calidad y completitud definidos para el inventario disponible en el incremento, sin declarar aptitud clínica o productiva.
- Un puerto de entrada que desacople la carga local de la lógica de ingesta.
- Un único acuse final con cantidades y códigos técnicos seguros por archivo. Los códigos no incluirán nombres, texto, valores clínicos, identificadores ni otro dato reidentificable.
- Pruebas con datos sintéticos y no identificantes.

### Excluye

- Persistencia de PDFs, texto, PII/PHI, datos anonimizados, resultados, archivos temporales o registros con contenido.
- Exponer la UI o el proceso fuera del equipo local, autenticación, API pública, integración hospitalaria, selector de carpetas, *watchers*, colas o *brokers*.
- Ecocardiografía, ECG —incluidas medidas textuales y señal de trazado—, vinculación longitudinal y seudonimización.
- Habilitación basada en corpus, métricas de calidad aprobadas, evaluación de calidad productiva o incorporación de muestras clínicas al repositorio.
- Datasets de ML, *features*, *targets*, entrenamiento o persistencia de datos para ML.
- Elegir tecnologías de persistencia, mensajería, fuentes remotas o mecanismos de transporte futuros.

## Flujo y límites de privacidad

La UI local entrega los bytes de cada PDF al adaptador de carga. Éste invoca el puerto de entrada de ingesta. El caso de uso clasifica el documento como laboratorio, extrae datos transitorios, anonimiza, ejecuta una validación residual independiente y comprueba las reglas de completitud disponibles. El contenido y los resultados transitorios se descartan tanto ante éxito como ante error. Sólo después de tratar el lote completo se compone el acuse seguro.

La UI deberá verificarse como accesible únicamente en el entorno local y sin exposición a red externa. La elección de la tecnología concreta para servirla no forma parte de esta propuesta; deberá respetar ese límite operativo.

## Entregas encadenadas

| PR | Resultado revisable | Límite |
| --- | --- | --- |
| PR 1 | Contratos de ingesta efímera, reglas de privacidad/completitud y adaptador de laboratorio en memoria. | Sin UI pública ni persistencia. |
| PR 2 | UI local de navegador, carga de lote y acuse seguro conectados al flujo de laboratorio. | Sin exponer contenido, red externa ni almacenamiento. |
| PR 3 | Evaluación de calidad para laboratorio. | Sólo tras aprobar corpus, inventario y umbrales. |
| PR 4 | Persistencia, si se autoriza. | Requiere propuesta y aprobación específicas de retención, esquema y privacidad. |
| PR 5+ | Ecocardiografía, ECG y capacidades de ML. | Cada familia o capacidad requiere aprobación y evidencia propias. |

## Capacidades

### Nuevas capacidades en el primer incremento

- `carga-manual-local`: recibe un lote de PDFs de laboratorio desde un navegador local y devuelve un acuse técnico seguro al finalizarlo.
- `ingesta-laboratorio-efimera`: procesa únicamente PDFs de laboratorio en memoria mediante un puerto de entrada y descarta sus salidas transitorias.
- `validacion-privacidad-local`: bloquea resultados con PII/PHI residual o controles incompletos sin retener contenido.

### Capacidades diferidas y bloqueadas

- `calidad-de-extraccion`: se habilitará sólo con corpus autorizado, inventario versionado y umbrales aprobados.
- Adaptadores de ecocardiografía y ECG: cada uno requerirá aprobación clínica, inventario, corpus y umbrales; ECG requerirá además una decisión explícita sobre el alcance de sus medidas y excluirá la señal de trazado salvo una aprobación posterior.
- Persistencia y auditoría: requieren una propuesta separada que defina retención, acceso, modelo de datos y controles de privacidad.
- Datasets de ML: requieren aprobaciones independientes sobre propósito, definición de *features*, gobernanza y, si aplica, *target*.

## Áreas afectadas

| Área | Impacto | Descripción |
| --- | --- | --- |
| `openspec/changes/ingesta-pdf-clinicos/` | Modificada | Plan y puertas de aprobación del cambio. |
| Futuro adaptador local de navegador | Nueva | Carga manual múltiple y acuse técnico seguro. |
| Futuro caso de uso y adaptador de laboratorio | Nuevo | Procesamiento efímero y desacoplado de la fuente local. |
| Futuro dominio de privacidad/completitud | Nuevo | Reglas transitorias que no exponen ni retienen datos clínicos. |

## Riesgos y mitigaciones

| Riesgo | Mitigación |
| --- | --- |
| PII/PHI residual durante la extracción | Procesamiento sólo en memoria, anonimización, validación residual independiente y pruebas sintéticas negativas. |
| El acuse se interpreta como resultado clínico | Limitarlo a contadores y códigos técnicos seguros; no mostrar observaciones, valores ni diagnósticos. |
| Variación de formatos de laboratorio | Limitar el primer alcance, declarar rechazos seguros y diferir habilitación por corpus hasta contar con evidencia aprobada. |
| Exposición accidental de la UI | Verificar ejecución exclusivamente local y sin publicación externa antes de aceptar el PR 2. |
| La falta de persistencia limita reintentos | Requerir una nueva carga desde la fuente autorizada; cualquier retención necesita aprobación separada. |

## Criterios de éxito

- [ ] Una persona puede arrastrar múltiples PDFs de laboratorio en una UI local y recibe un único acuse al finalizar el lote completo.
- [ ] Cada PDF completa extracción transitoria, anonimización, validación residual y controles de completitud antes de descartarse.
- [ ] El acuse contiene sólo cantidades y códigos técnicos seguros; no contiene datos clínicos, texto, PII/PHI ni resultados detallados.
- [ ] No se crean persistencia, temporales, registros con contenido, colas ni integraciones remotas.
- [ ] El flujo de carga local invoca un puerto de entrada sin acoplar la lógica de ingesta a la UI.
- [ ] Ninguna capacidad diferida se inicia sin la aprobación y evidencia indicadas en este documento.
