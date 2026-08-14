# Tareas: Ingesta local y efímera de PDFs de laboratorio

## Estrategia de entrega y revisión

Se cierra la primera entrega revisable (PR 1) con aproximadamente 357 líneas modificadas, cerca del presupuesto de 400 líneas. Las secciones 1.1 y 1.2 completaron RED, GREEN, TRIANGULATE y REFACTOR. La sección 1.3 no se inició: se traslada completa al siguiente PR para no ampliar el cierre actual. La planificación no autoriza implementar PR 4 ni posteriores: cada uno requiere las puertas expresadas abajo.

| PR | Objetivo | Dependencia | Fuera de alcance |
| --- | --- | --- | --- |
| PR 1 — cerrado | Núcleo efímero y adaptador sintético de laboratorio en memoria (1.1 y 1.2). | Ninguna adicional. | `PrivacyValidator`, UI, persistencia, calidad habilitable y otras familias. |
| PR 2 — siguiente | Privacidad y límites operativos trasladados de 1.3. | PR 1 cerrado. | UI, persistencia, calidad habilitable y otras familias. |
| PR 3 | UI local de navegador y acuse seguro del lote. | PR 2 integrado. | Red externa, almacenamiento y otras familias. |
| PR 4 | Evaluación de calidad de laboratorio. | Corpus, inventario y umbrales aprobados. | Persistencia y familias adicionales. |
| PR 5 | Persistencia, si procede. | Propuesta separada aprobada. | Ecocardiografía, ECG y ML salvo aprobación separada. |
| PR 6+ | Ecocardiografía, ECG o datasets de ML. | Aprobaciones y evidencia específicas por capacidad. | Cualquier capacidad no aprobada. |

## PR 1 — Cerrado: núcleo efímero y adaptador de laboratorio

### 1.1 Contratos, estados y política de decisión

- [x] RED: crear pruebas unitarias que fijen los estados exhaustivos (`verified`, `not_present`, `missing`, `ambiguous`, `malformed`, `truncated`), la resolución explícita de los campos del inventario disponible y el rechazo por PII/PHI residual, controles incompletos o campos requeridos no verificables. Completado en PR 1. <!-- sdd-owner: implementation -->
- [x] GREEN: implementar los tipos puros, `IngestionInputPort`, `ExtractionResult` efímero y la política de decisión que produzca sólo aprobación técnica o códigos/conteos no identificantes. Ningún tipo de salida contendrá PDF, texto fuente, PII/PHI, valores clínicos, identificadores ni fechas reidentificantes. Completado en PR 1. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: añadir casos de unidades incompatibles, valores malformados o truncados, candidatos múltiples y ausencia legítima opcional; comprobar que ningún campo se omite silenciosamente. Completado en PR 1. <!-- sdd-owner: implementation -->
- [x] REFACTOR: separar reglas puras de los detalles PDF y mantener las pruebas verdes; documentar en la evidencia el comando de prueba realmente detectado, sin asumir un *runner*. Completado en PR 1. <!-- sdd-owner: implementation -->

### 1.2 Extracción en memoria limitada a laboratorio

- [x] RED: añadir pruebas con texto o bloques sintéticos y no identificantes para clasificación de laboratorio, procedencia técnica transitoria y conversión al contrato; no incorporar PDFs reales ni *fixtures* clínicos. Completado en PR 1. <!-- sdd-owner: implementation -->
- [x] GREEN: implementar `LaboratoryFamilyAdapter` y el extractor de PDF en memoria con la biblioteca elegida al iniciar la implementación. El adaptador recibirá bytes o flujos efímeros, los descartará al terminar y rechazará de forma segura documentos que no sean de laboratorio. Completado en PR 1. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: ampliar pruebas para orden de lectura variable, filas de tabla incompletas y dos candidatos, comprobando estados y procedencia sin conservar texto extraído. Completado en PR 1. <!-- sdd-owner: implementation -->
- [x] REFACTOR: aislar el mapeo de laboratorio detrás del adaptador; verificar que dominio y aplicación no dependan de la biblioteca PDF y que no se agregan OCR, `pdfplumber`, persistencia ni temporales. Completado en PR 1. <!-- sdd-owner: implementation -->

### 1.3 Privacidad y límites operativos

No iniciada. Se traslada íntegramente a PR 2 para cerrar PR 1 cerca del presupuesto de revisión; no forma parte del estado completado de PR 1.

### 1.4 Cierre revisable de PR 1

- [x] Ejecutar las pruebas del PR y registrar comandos, resultados y limitaciones sin incluir contenido clínico. Evidencia corregida: el 2026-08-14, `.venv/Scripts/python.exe -m pytest` finalizó con 25 pruebas aprobadas y árbol limpio. <!-- sdd-owner: implementation -->
- [x] Revisar que el diff se mantenga aproximadamente dentro de 400 líneas; dividir trabajo pendiente antes de incorporar UI u otra capacidad. PR 1 se cierra con aproximadamente 357 líneas modificadas y 1.3 se difiere a PR 2. <!-- sdd-owner: parent -->

## PR 2 — Privacidad y límites operativos

### 2.1 Privacidad y descarte transitorio

- [x] RED: incorporar casos negativos para el validador residual independiente que demuestren que un hallazgo de PII/PHI bloquea el archivo y que la salida sólo contiene códigos y conteos permitidos. Completado con pruebas sintéticas de bloqueo residual y límite de salida. <!-- sdd-owner: implementation -->
- [x] GREEN: implementar `PrivacyValidator` en memoria y conectar anonimización, validación residual y política de decisión al flujo de laboratorio. Completado mediante validador inyectable y anonimización explícita previa. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: cubrir errores de extracción y fallos de validación aplicables sin lote, demostrando descarte del contenido transitorio tanto en éxito como en error. El lote parcial se difiere explícitamente a PR 3 porque PR 2 no implementa procesamiento por lote. <!-- sdd-owner: implementation -->
- [x] REFACTOR: revisar que no se escriben archivos, no hay logs de contenido, base de datos, migraciones, colas ni *brokers*; mantener la comprobación automatizada correspondiente en verde. Completado con comprobación automatizada de dependencias laterales prohibidas. <!-- sdd-owner: implementation -->

### 2.2 Cierre revisable de PR 2

- [x] Ejecutar las pruebas del PR y registrar comandos, resultados y limitaciones sin incluir contenido clínico. Completado: 31 pruebas aprobadas con `.venv/Scripts/python.exe -m pytest`. Limitación: no existe lote en PR 2. <!-- sdd-owner: implementation -->
- [ ] Revisar que el diff se mantenga aproximadamente dentro de 400 líneas antes de incorporar UI u otra capacidad. <!-- sdd-owner: parent -->

## PR 3 — UI local y acuse seguro de lote

### 3.1 Carga local desacoplada

- [x] RED: crear pruebas del adaptador de UI que fijen carga múltiple, invocación del `IngestionInputPort` por archivo y emisión de un único acuse sólo después de terminar el lote. Completado en PR 3 con `tests/test_carga_local_pr3.py`. <!-- sdd-owner: implementation -->
- [x] GREEN: implementar una UI de navegador exclusivamente local para arrastrar PDFs y un adaptador que entregue cada archivo al puerto de entrada sin acoplarse a extracción o privacidad. Completado en PR 3 mediante vista estática local y `AdaptadorCargaLocal`. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: cubrir archivos no laboratorio, errores por archivo, lotes mixtos y lote parcial; comprobar que el acuse conserva sólo cantidades y códigos técnicos seguros. Completado en PR 3 con lote mixto/parcial y normalización segura. <!-- sdd-owner: implementation -->
- [x] REFACTOR: eliminar cualquier exposición de resultados transitorios de la UI y simplificar el límite entre adaptador y caso de uso sin romper las pruebas. Completado en PR 3: se aisló el procesamiento efímero por archivo. <!-- sdd-owner: implementation -->

### 3.2 Verificación de límites locales

- [x] RED: añadir pruebas o comprobaciones automatizables que fallen si el acuse contiene texto extraído, PII/PHI, valores clínicos, observaciones o diagnósticos. Completado en PR 3 con casos negativos de acuse y contenido de UI. <!-- sdd-owner: implementation -->
- [x] GREEN: configurar la ejecución necesaria para operar sólo localmente, sin publicar un servicio en red externa; no agregar autenticación, API pública, almacenamiento, colas ni *broker*. Completado en PR 3 con UI estática sin servicio ni dependencias de red. <!-- sdd-owner: implementation -->
- [x] TRIANGULATE: verificar manualmente y con pruebas que no se crean temporales ni logs de contenido durante éxito, error y lote parcial. Completado en PR 3 con comprobación automatizada de dependencias laterales y ejecuciones de lote. <!-- sdd-owner: implementation -->
- [x] REFACTOR: conservar sólo la configuración mínima necesaria para la UI local y mantener todas las comprobaciones verdes. Completado en PR 3: sólo se conserva marcado estático local. <!-- sdd-owner: implementation -->

### 3.3 Cierre revisable de PR 3

- [x] Ejecutar pruebas y comprobaciones manuales del límite local; registrar comandos reales, resultados y limitaciones sin datos sensibles. Completado en PR 3: 43 pruebas aprobadas y `git diff --check` sin errores. <!-- sdd-owner: implementation -->
- [x] Revisar el tamaño del diff y confirmar que el PR no introduce persistencia, evaluación habilitable, ECG, ecocardiografía ni ML. Confirmado el 2026-08-14: código y pruebas de PR 3 suman 263 líneas (`git diff --no-index`), sin persistencia, evaluación habilitable, ECG, ecocardiografía, ML, red externa, autenticación, API pública, colas ni brokers. `docs/architecture/diagrama.md` se difiere a un commit de documentación aparte para no mezclar alcance ni presupuesto de líneas. <!-- sdd-owner: parent -->

## Trabajo diferido — no iniciar sin puerta aprobada

### PR 4 — Evaluación de calidad de laboratorio

- [ ] Puerta: recibir corpus autorizado, inventario versionado y umbrales numéricos aprobados de cobertura, exactitud de valor/unidad, omisiones, rechazos y PII residual. <!-- sdd-owner: parent -->
- [ ] Tras la puerta, aplicar TDD estricto para un evaluador por campo y versión que use el corpus autorizado fuera del repositorio y publique sólo métricas técnicas permitidas. <!-- sdd-owner: implementation -->

### PR 5 — Persistencia

- [ ] Puerta: aprobar una propuesta separada sobre propósito, retención, acceso, esquema, trazabilidad y controles de privacidad; decidir entonces la tecnología de almacenamiento. <!-- sdd-owner: parent -->
- [ ] Tras la puerta, aplicar TDD estricto para persistir sólo los datos explícitamente autorizados y demostrar que PDF, texto fuente, PII/PHI y rechazos no se retienen. <!-- sdd-owner: implementation -->

### PR 6+ — Ecocardiografía, ECG y datasets de ML

- [ ] Puerta para ecocardiografía: aprobación clínica y de privacidad, inventario, corpus y umbrales propios. <!-- sdd-owner: parent -->
- [ ] Puerta para ECG: aprobación equivalente y definición explícita del alcance; la señal de trazado exige una fuente nativa validada y aprobación independiente. <!-- sdd-owner: parent -->
- [ ] Puerta para ML: aprobación de propósito, gobernanza, *features* versionadas, condiciones de calidad y, si corresponde, *target*. <!-- sdd-owner: parent -->
- [ ] Tras cada puerta, planificar un PR independiente con RED, GREEN, TRIANGULATE y REFACTOR antes de implementar. <!-- sdd-owner: implementation -->
