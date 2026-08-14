# Diseño: Ingesta local y efímera de PDFs de laboratorio

## Decisión

Se cierra la primera entrega revisable con el núcleo efímero y el adaptador sintético de laboratorio en memoria. Las secciones 1.1 y 1.2 completaron RED, GREEN, TRIANGULATE y REFACTOR, con aproximadamente 357 líneas modificadas. La sección 1.3 —privacidad y límites operativos— no se inició y se traslada íntegramente a la siguiente entrega encadenada, antes de incorporar la UI.

El flujo objetivo seguirá siendo local, en memoria y limitado a PDFs de laboratorio. Una UI de navegador local cargará un lote de archivos y recibirá, al finalizarlo, un acuse técnico seguro en una entrega posterior. El sistema no persistirá datos ni utilizará PostgreSQL, migraciones, colas, *brokers*, fuentes remotas o conjuntos de datos de ML.

```text
Navegador local
  → adaptador de carga de lote
  → puerto de entrada de ingesta
  → clasificación de laboratorio y extracción en memoria
  → anonimización + validación residual + completitud
  → descarte de datos transitorios
  → acuse técnico seguro del lote
```

La arquitectura separa la fuente de entrada del caso de uso, para no acoplar la extracción a la UI. Esa separación no autoriza adaptadores de red, almacenamiento ni otras familias documentales en esta entrega.

## Límites no negociables del primer incremento

| Área | Decisión |
| --- | --- |
| Familia documental | Sólo laboratorio. Un PDF que no corresponda a laboratorio se rechaza mediante un código técnico seguro. |
| Ejecución | Local, síncrona y en memoria. Cada archivo se descarta al concluir, tanto ante éxito como ante error. |
| UI | Navegador local, carga múltiple y acuse final de lote. No se expone a red externa ni muestra datos extraídos. |
| Salida | Contadores y códigos técnicos no identificantes; nunca PDF, texto fuente, PII/PHI, valores clínicos, diagnósticos u observaciones. |
| Datos y operación | Sin persistencia, archivos temporales, logs de contenido, base de datos, migraciones, colas ni *broker*. |
| Pruebas | Datos sintéticos y no identificantes; no se versionan PDFs clínicos ni corpus sensibles. |

## Contratos y flujo

Los contratos expresan necesidades del núcleo y mantienen el procesamiento independiente de la UI:

- `IngestionInputPort`: recibe los bytes o flujo efímero de un documento y devuelve únicamente un resultado técnico seguro.
- `LaboratoryFamilyAdapter`: decide si el documento es de laboratorio y construye un resultado de extracción efímero usando datos en memoria.
- `PrivacyValidator`: comprueba la anonimización y PII/PHI residual mediante una validación independiente.
- `BatchAcknowledgement`: compone al final del lote las cantidades y códigos seguros por archivo que la UI puede mostrar.

`ExtractionResult` es efímero. Para cada campo resuelto del inventario disponible utiliza exactamente uno de estos estados: `verified`, `not_present`, `missing`, `ambiguous`, `malformed` o `truncated`. Puede incluir procedencia técnica mínima necesaria para la decisión durante la ejecución, pero ésta no cruza al acuse ni se conserva.

La política de decisión bloquea un documento si encuentra PII/PHI residual, un control de privacidad incompleto o un campo requerido no verificable. El resultado permitido es una decisión técnica y códigos/conteos no identificantes. No existirá `ApprovedObservationStore` ni ningún equivalente en este incremento.

## Diseño por PR encadenado

### PR 1 — Cerrado: núcleo efímero y laboratorio en memoria

Completó contratos, estados, política de decisión y adaptador sintético de laboratorio que opera sobre datos en memoria. Las secciones 1.1 y 1.2 cuentan con evidencia RED, GREEN, TRIANGULATE y REFACTOR para resultados válidos, campos ausentes, valores malformados, candidatos ambiguos y variantes de bloques sintéticos. No incluye `PrivacyValidator`, UI de usuario ni persistencia.

### PR 2 — Siguiente: privacidad y límites operativos

Recibe sin cambios de alcance la sección 1.3: `PrivacyValidator` en memoria, conexión de anonimización, validación residual independiente y política de decisión al flujo de laboratorio. Sus pruebas deberán cubrir hallazgos de PII/PHI, errores de extracción, fallos de validación y descarte de contenido transitorio en éxito y error. No incorpora UI ni persistencia.

### PR 3 — UI local y acuse de lote

Añade el adaptador de navegador local, carga múltiple y composición del acuse final, una vez integrado PR 2. La UI no recibe resultados clínicos transitorios. Las pruebas cubren que el acuse se emite al final del lote, que sólo contiene datos permitidos y que los fallos por archivo no exponen contenido. Se verifica además la operación local sin publicación externa.

Cada PR debe mantener un tamaño aproximado de 400 líneas modificadas. PR 1 se cierra cerca de ese presupuesto, con aproximadamente 357 líneas modificadas; por ese motivo la sección 1.3 se entrega en PR 2 y no se agrega al cierre actual.

## Calidad y verificación del incremento

Se aplicará TDD estricto: RED para fijar el contrato y los límites de privacidad, GREEN para la mínima implementación y TRIANGULATE para variantes de formato y errores; REFACTOR sólo después de mantener la evidencia verde. La verificación incluirá pruebas unitarias y de integración acotada con datos sintéticos, además de una comprobación manual de que el flujo no crea archivos, no depende de red ni deja contenido en la UI o logs.

El primer incremento no declara precisión clínica, cobertura de formatos ni aptitud productiva. Hasta tener evidencia aprobada, los formatos no manejados se rechazan con códigos seguros.

## Capacidades diferidas y puertas

| Capacidad | Puerta antes de diseñar o implementar |
| --- | --- |
| Evaluación de calidad de laboratorio (PR 4) | Corpus autorizado, inventario versionado y umbrales de cobertura, exactitud, omisiones, rechazos y PII residual aprobados. |
| Persistencia (PR 5) | Nueva propuesta aprobada que establezca necesidad, retención, acceso, esquema, trazabilidad y controles de privacidad. La tecnología se decide entonces. |
| Ecocardiografía | Aprobación clínica y de privacidad, inventario propio, corpus autorizado y umbrales por familia. |
| ECG | Aprobación equivalente; alcance explícito de medidas. La señal del trazado queda excluida hasta contar con fuente nativa validada y aprobación independiente. |
| Vínculo longitudinal | Decisión explícita de producto y privacidad sobre seudonimización, retención y acceso. |
| Datasets de ML | Aprobación de propósito, gobernanza, definición versionada de *features*, condiciones de calidad y, si corresponde, *target*. |

## Preguntas abiertas fuera de este incremento

- ¿Qué inventario de campos de laboratorio, reglas de requeridos y códigos técnicos se aprobarán para la evaluación posterior?
- ¿Qué corpus autorizado y umbrales se utilizarán para habilitar versiones de extracción?
- ¿Qué necesidad de negocio justificaría una futura retención y bajo qué controles?

Estas preguntas no bloquean la planificación del flujo efímero; sí bloquean las capacidades indicadas en la tabla de puertas.
