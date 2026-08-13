# Tareas: Ingesta local y efímera de PDFs de laboratorio

## Estrategia de entrega y revisión

La primera entrega se divide en dos PRs encadenados para sostener un tamaño revisable de aproximadamente 400 líneas modificadas por PR. La planificación no autoriza implementar PR 3 ni posteriores: cada uno requiere las puertas expresadas abajo.

| PR | Objetivo | Dependencia | Fuera de alcance |
| --- | --- | --- | --- |
| PR 1 | Núcleo efímero, privacidad y adaptador de laboratorio en memoria. | Ninguna adicional. | UI, persistencia, calidad habilitable, otras familias. |
| PR 2 | UI local de navegador y acuse seguro del lote. | PR 1 integrado. | Red externa, almacenamiento, otras familias. |
| PR 3 | Evaluación de calidad de laboratorio. | Corpus, inventario y umbrales aprobados. | Persistencia y familias adicionales. |
| PR 4 | Persistencia, si procede. | Propuesta separada aprobada. | Ecocardiografía, ECG y ML salvo aprobación separada. |
| PR 5+ | Ecocardiografía, ECG o datasets de ML. | Aprobaciones y evidencia específicas por capacidad. | Cualquier capacidad no aprobada. |

## PR 1 — Núcleo efímero y adaptador de laboratorio

### 1.1 Contratos, estados y política de decisión

- [ ] RED: crear pruebas unitarias que fijen los estados exhaustivos (`verified`, `not_present`, `missing`, `ambiguous`, `malformed`, `truncated`), la resolución explícita de los campos del inventario disponible y el rechazo por PII/PHI residual, controles incompletos o campos requeridos no verificables. <!-- sdd-owner: implementation -->
- [ ] GREEN: implementar los tipos puros, `IngestionInputPort`, `ExtractionResult` efímero y la política de decisión que produzca sólo aprobación técnica o códigos/conteos no identificantes. Ningún tipo de salida contendrá PDF, texto fuente, PII/PHI, valores clínicos, identificadores ni fechas reidentificantes. <!-- sdd-owner: implementation -->
- [ ] TRIANGULATE: añadir casos de unidades incompatibles, valores malformados o truncados, candidatos múltiples y ausencia legítima opcional; comprobar que ningún campo se omite silenciosamente. <!-- sdd-owner: implementation -->
- [ ] REFACTOR: separar reglas puras de los detalles PDF y mantener las pruebas verdes; documentar en la evidencia el comando de prueba realmente detectado, sin asumir un *runner*. <!-- sdd-owner: implementation -->

### 1.2 Extracción en memoria limitada a laboratorio

- [ ] RED: añadir pruebas con texto o bloques sintéticos y no identificantes para clasificación de laboratorio, procedencia técnica transitoria y conversión al contrato; no incorporar PDFs reales ni *fixtures* clínicos. <!-- sdd-owner: implementation -->
- [ ] GREEN: implementar `LaboratoryFamilyAdapter` y el extractor de PDF en memoria con la biblioteca elegida al iniciar la implementación. El adaptador recibirá bytes o flujos efímeros, los descartará al terminar y rechazará de forma segura documentos que no sean de laboratorio. <!-- sdd-owner: implementation -->
- [ ] TRIANGULATE: ampliar pruebas para orden de lectura variable, filas de tabla incompletas y dos candidatos, comprobando estados y procedencia sin conservar texto extraído. <!-- sdd-owner: implementation -->
- [ ] REFACTOR: aislar el mapeo de laboratorio detrás del adaptador; verificar que dominio y aplicación no dependan de la biblioteca PDF y que no se agregan OCR, `pdfplumber`, persistencia ni temporales. <!-- sdd-owner: implementation -->

### 1.3 Privacidad y límites operativos

- [ ] RED: incorporar casos negativos para el validador residual independiente que demuestren que un hallazgo de PII/PHI bloquea el archivo y que la salida sólo contiene códigos y conteos permitidos. <!-- sdd-owner: implementation -->
- [ ] GREEN: implementar `PrivacyValidator` en memoria y conectar anonimización, validación residual y política de decisión al flujo de laboratorio. <!-- sdd-owner: implementation -->
- [ ] TRIANGULATE: cubrir errores de extracción, fallos de validación y lote parcial, demostrando descarte del contenido transitorio tanto en éxito como en error. <!-- sdd-owner: implementation -->
- [ ] REFACTOR: revisar que no se escriben archivos, no hay logs de contenido, base de datos, migraciones, colas ni *brokers*; mantener la comprobación automatizada correspondiente en verde. <!-- sdd-owner: implementation -->

### 1.4 Cierre revisable de PR 1

- [ ] Ejecutar las pruebas del PR y registrar comandos, resultados y limitaciones sin incluir contenido clínico. <!-- sdd-owner: implementation -->
- [ ] Revisar que el diff se mantenga aproximadamente dentro de 400 líneas; dividir trabajo pendiente antes de incorporar UI u otra capacidad. <!-- sdd-owner: parent -->

## PR 2 — UI local y acuse seguro de lote

### 2.1 Carga local desacoplada

- [ ] RED: crear pruebas del adaptador de UI que fijen carga múltiple, invocación del `IngestionInputPort` por archivo y emisión de un único acuse sólo después de terminar el lote. <!-- sdd-owner: implementation -->
- [ ] GREEN: implementar una UI de navegador exclusivamente local para arrastrar PDFs y un adaptador que entregue cada archivo al puerto de entrada sin acoplarse a extracción o privacidad. <!-- sdd-owner: implementation -->
- [ ] TRIANGULATE: cubrir archivos no laboratorio, errores por archivo y lotes mixtos; comprobar que el acuse conserva sólo cantidades y códigos técnicos seguros. <!-- sdd-owner: implementation -->
- [ ] REFACTOR: eliminar cualquier exposición de resultados transitorios de la UI y simplificar el límite entre adaptador y caso de uso sin romper las pruebas. <!-- sdd-owner: implementation -->

### 2.2 Verificación de límites locales

- [ ] RED: añadir pruebas o comprobaciones automatizables que fallen si el acuse contiene texto extraído, PII/PHI, valores clínicos, observaciones o diagnósticos. <!-- sdd-owner: implementation -->
- [ ] GREEN: configurar la ejecución necesaria para operar sólo localmente, sin publicar un servicio en red externa; no agregar autenticación, API pública, almacenamiento, colas ni *broker*. <!-- sdd-owner: implementation -->
- [ ] TRIANGULATE: verificar manualmente y con pruebas que no se crean temporales ni logs de contenido durante éxito, error y lote parcial. <!-- sdd-owner: implementation -->
- [ ] REFACTOR: conservar sólo la configuración mínima necesaria para la UI local y mantener todas las comprobaciones verdes. <!-- sdd-owner: implementation -->

### 2.3 Cierre revisable de PR 2

- [ ] Ejecutar pruebas y comprobaciones manuales del límite local; registrar comandos reales, resultados y limitaciones sin datos sensibles. <!-- sdd-owner: implementation -->
- [ ] Revisar el tamaño del diff y confirmar que el PR no introduce persistencia, evaluación habilitable, ECG, ecocardiografía ni ML. <!-- sdd-owner: parent -->

## Trabajo diferido — no iniciar sin puerta aprobada

### PR 3 — Evaluación de calidad de laboratorio

- [ ] Puerta: recibir corpus autorizado, inventario versionado y umbrales numéricos aprobados de cobertura, exactitud de valor/unidad, omisiones, rechazos y PII residual. <!-- sdd-owner: parent -->
- [ ] Tras la puerta, aplicar TDD estricto para un evaluador por campo y versión que use el corpus autorizado fuera del repositorio y publique sólo métricas técnicas permitidas. <!-- sdd-owner: implementation -->

### PR 4 — Persistencia

- [ ] Puerta: aprobar una propuesta separada sobre propósito, retención, acceso, esquema, trazabilidad y controles de privacidad; decidir entonces la tecnología de almacenamiento. <!-- sdd-owner: parent -->
- [ ] Tras la puerta, aplicar TDD estricto para persistir sólo los datos explícitamente autorizados y demostrar que PDF, texto fuente, PII/PHI y rechazos no se retienen. <!-- sdd-owner: implementation -->

### PR 5+ — Ecocardiografía, ECG y datasets de ML

- [ ] Puerta para ecocardiografía: aprobación clínica y de privacidad, inventario, corpus y umbrales propios. <!-- sdd-owner: parent -->
- [ ] Puerta para ECG: aprobación equivalente y definición explícita del alcance; la señal de trazado exige una fuente nativa validada y aprobación independiente. <!-- sdd-owner: parent -->
- [ ] Puerta para ML: aprobación de propósito, gobernanza, *features* versionadas, condiciones de calidad y, si corresponde, *target*. <!-- sdd-owner: parent -->
- [ ] Tras cada puerta, planificar un PR independiente con RED, GREEN, TRIANGULATE y REFACTOR antes de implementar. <!-- sdd-owner: implementation -->
