# Tasks: señal de ECG y dataset vinculado

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 1.100–1.300 (350 + 300 + 350 + 150, según proposal.md) |
| 400-line budget risk | Low por entrega individual; Medium si se mira el cambio completo |
| Chained PRs recommended | Yes |
| Suggested split | PR1 extracción+sintéticos → PR2 dominio/persistencia/completitud → PR3 exportación → PR4 verificador PII + cierre fase 5 |
| Delivery strategy | ask-on-risk |
| Chain strategy | pendiente de confirmar con el usuario (stacked-to-main vs feature-branch-chain) |

Decision needed before apply: Yes — confirmar chain strategy antes de `sdd-apply`. Ninguna entrega individual supera los ~400 líneas estimadas en la propuesta, pero por tratarse de 4 PRs encadenados corresponde fijar la estrategia de cadena (mismo patrón que `operacion-segura-y-escalable`, que usó `feature-branch-chain`).

### Alineación spec/diseño detectada en esta fase

- **Nombre del campo de completitud**: la spec de `extraccion-senal-ecg` y de `document-parsing` usan literal `senal` en `campos_no_extraidos`; el diseño usa `ecg.senal` (ver diagrama de secuencia y tabla de Archivos, `dominio/referencias.py`). Se toma el nombre del **diseño** (`ecg.senal`, namespaced por tipo de documento, consistente con cómo ya se nombran otros campos no extraídos en `dominio/referencias.py`). Tarea 2.0 alinea las specs.
- **`anonymized-output` MAY exportar**: sin desalineación — la spec ya refleja el diseño (Postgres como única fuente de verdad, exportación derivada opcional). No requiere tarea de corrección.

## Phase 1: Extracción + trazos sintéticos (PR 1, ~350 líneas)

Rollback boundary: revertir el PR completo no afecta nada existente (nuevo código, sin tocar `pipeline/ejecutor.py` aún salvo el punto de inyección). Verificación: `pytest tests/extraccion/ tests/fixtures/test_pdf_sintetico_ecg.py`.

- [x] 1.1 **RED**: crear `tests/extraccion/test_trazos_pymupdf.py` con un PDF sintético mínimo rotado 90° que dibuja un rectángulo conocido; fijar si `get_drawings()` devuelve coordenadas rotadas o sin rotar respecto de `page.derotation_matrix` (pregunta abierta del diseño, decisión #1 del algoritmo).
- [x] 1.2 **GREEN**: crear `src/anonimizacion/extraccion/trazos_pymupdf.py`: captura de trazos negros (0,0,0) sin relleno vía `get_drawings()`, proyección a espacio sin rotar y a mm, según lo fijado en 1.1.
- [x] 1.3 **RED/GREEN**: crear `src/anonimizacion/extraccion/registro_trazos.py`: registro `{ECG: capturador}` inyectable; extender `extraccion/texto_pymupdf.py` con `extraer_texto_de_flujo(flujo, *, capturador_para=None)` y `TextoExtraido.trazos = ()` por defecto; probar en `tests/extraccion/test_texto_pymupdf.py` que los otros 2 tipos de documento no invocan captura de trazos.
- [x] 1.4 **RED/GREEN**: crear `src/anonimizacion/dominio/senal_ecg.py` (`SenalEcg` frozen, `eq=False`, `__repr__` sin volcar muestras) y `src/anonimizacion/extraccion/senal_ecg.py` (`construir_senal`, puro numpy): calibración por 4 pulsos, asignación por fila/columna, conversión a 500 Hz, validación estricta todo-o-nada; probar con polilíneas sintéticas equiespaciadas, no equiespaciadas y cada violación de layout en `tests/extraccion/test_senal_ecg.py`.
- [x] 1.5 **RED/GREEN**: extender `tests/fixtures/pdf_sintetico.py` (y `plantilla_documento.py` si aplica) para dibujar trazos de ECG con oráculo conocido (layout de la spec: 4×3 columnas, offsets 0/2,5/5/7,5 s, 4 pulsos de calibración, escala 25 mm/s y 10 mm/mV); probar en `tests/fixtures/test_pdf_sintetico_ecg.py` que `construir_senal` recupera la señal del oráculo con error ≤ 0,01 mV en cada derivación (criterio de éxito de la propuesta).
- [x] 1.6 **REFACTOR**: revisar cobertura de `noqa: C901` — si `construir_senal` supera el límite de complejidad, descomponer en sub-pasos con nombre propio (mismo criterio que otros parsers calibrados, ver `pyproject.toml`).

## Phase 2: Dominio + persistencia + completitud (PR 2, ~300 líneas)

Depende de PR 1 (usa `SenalEcg` y `construir_senal`). Rollback boundary: el downgrade de la migración `0013` elimina `senal_ecg` sin afectar `estudio`; revertir el PR no requiere backfill (diseño, sección Migración).

- [ ] 2.0 **Alineación de specs**: actualizar `openspec/changes/senal-ecg-y-dataset-vinculado/specs/extraccion-senal-ecg/spec.md` y `specs/document-parsing/spec.md` para que el nombre del campo en `campos_no_extraidos` sea `ecg.senal` (consistente con el diseño y con `dominio/referencias.py`), no `senal` suelto.
- [ ] 2.1 **RED/GREEN**: crear `src/anonimizacion/salida/codec_senal.py` (codificación `int16` µV little-endian + zlib para la señal, `packbits` + zlib para la máscara) con ida y vuelta probada en `tests/salida/test_codec_senal.py`.
- [ ] 2.2 **RED/GREEN**: crear migración `migrations/versions/0013_senal_ecg.py`: tabla `senal_ecg` (PK = FK `id_estudio`, `ON DELETE CASCADE`, `SET STORAGE EXTERNAL` sólo en Postgres); probar upgrade/downgrade en `tests/salida/test_migraciones.py`.
- [ ] 2.3 **RED/GREEN**: extender `src/anonimizacion/salida/modelos_orm.py` con el modelo ORM de `senal_ecg`; extender `dominio/modelos.py` (`ContenidoEcg.senal: SenalEcg | None = None`) y `salida/modelos_salida.py` (`ContenidoEcgSalida.senal`); probar serialización en `tests/dominio/test_modelos.py` y `tests/salida/test_modelos_salida.py`.
- [ ] 2.4 **RED/GREEN**: modificar `parseo/ecg_mortara.py` para invocar `construir_senal` sobre los trazos capturados (vía el registro de 1.3) y modificar `reconciliacion/ecg_mortara.py` para agregar `ecg.senal` a `campos_no_extraidos` cuando `senal=None`, sin cuarentena por ese motivo; probar en `tests/parseo/test_ecg_mortara.py` y `tests/reconciliacion/test_ecg_mortara.py` los 3 escenarios de la spec (señal válida, señal inválida, advertencia de equipo tolerada).
- [ ] 2.5 **RED/GREEN**: modificar `dominio/referencias.py` para registrar `ecg.senal` como campo no extraído válido; modificar `pipeline/ejecutor.py` para inyectar el capturador de trazos (vía `registro_trazos.py`) al abrir el PDF una sola vez, y para persistir `estudio` + `medicion_ecg` + `senal_ecg` en una sola transacción; modificar `salida/constructor_registro.py` y `salida/destinos/postgres.py` para escribir la señal; probar idempotencia por `clave_documento` en `tests/pipeline/test_ejecutor.py` (reintento no duplica `senal_ecg`).
- [ ] 2.6 **REFACTOR**: revisar que `pipeline/ejecutor.py` no llame `detectar_tipo` más de dos veces por documento (decisión #1 del diseño) y que los fakes de tests existentes sigan pasando sin cambios de contrato en `extraer_texto_de_flujo` para laboratorio/eco.

## Phase 3: Exportación (PR 3, ~350 líneas)

Depende de PR 2 (lee `senal_ecg`, `estudio` y las tablas de laboratorio/eco ya existentes). Rollback boundary: la exportación sólo lee de Postgres — revertir el PR no requiere migración ni afecta datos persistidos.

- [ ] 3.1 **RED**: crear `tests/salida/test_exportacion.py` fijando el esquema exacto (lista blanca de columnas) de cada Parquet (`episodios`, `ecg`, `laboratorio`, `eco`) contra la spec de cero PII; confirmar que `clave_documento`, `corrida_id`, `id_medico*` y el texto libre del eco quedan afuera.
- [ ] 3.2 **GREEN**: crear `src/anonimizacion/salida/exportacion.py`: streaming en una transacción `REPEATABLE READ`, paginación por clave (lotes de 256), un `ParquetWriter` por tabla con un row group por lote, escritura en `<salida>.tmp` con rename atómico; vinculación de episodio por `patient_id` + ventana de 7 días (reutilizando o extendiendo `pseudonimizacion/vinculacion.py` si aplica) marcando campos faltantes sin descartar episodios incompletos.
- [ ] 3.3 **RED/GREEN**: generar `manifiesto.json` (versión de formato, 500 Hz, unidad/escala, orden de las 12 derivaciones + tira de ritmo, forma `FixedSizeList<int16>[60000]` + máscara, ventanas de vinculación, conteos, sha256 de cada archivo); probar en `tests/salida/test_exportacion.py` que el manifiesto declara exactamente lo que el diseño especifica.
- [ ] 3.4 **RED/GREEN**: agregar constantes de contrato (`EsquemaPdf`, copiadas, sin importar `modelo_hvi`) y test de contrato: decimar ×2 la señal exportada da (12, 2500) con 619 muestras por derivación coincidiendo con `EsquemaPdf`, sin otra transformación (`tests/salida/test_contrato_modelo_hvi.py`).
- [ ] 3.5 **RED/GREEN**: agregar subcomando `exportar` en `cli.py`; probar en `tests/test_cli.py` que no muta Postgres (comparar snapshot de filas antes/después) y que produce Parquet + manifiesto sobre un corpus sintético con episodios completos e incompletos.
- [ ] 3.6 **Dependencias**: decidir y regenerar `uv.lock` tras declarar `numpy>=1.26` y `pyarrow>=15` en `pyproject.toml` (dependencias base, no extra opcional — decisión #8 del diseño). El repo fija dependencias en `pyproject.toml` sin `requirements*.txt`; `uv.lock` no está en `.gitignore`, así que corresponde versionarlo. Ejecutar `uv lock` y commitear el lockfile regenerado junto con el cambio de `pyproject.toml` en la misma unidad de trabajo (evitar el estado actual de `uv.lock` sin versionar detectado en git status).

## Phase 4: Verificador PII lineal + cierre fase 5 de `operacion-segura-y-escalable` (PR 4, ~150 líneas)

Depende de PR 3 (audita la exportación). Rollback boundary: el verificador es una herramienta de auditoría, sin efecto en datos; revertir el PR no afecta el pipeline productivo.

- [ ] 4.1 **RED**: crear `tests/fixtures/verificador_pii.py` con semillas de prueba y una versión de referencia cuadrática (fuerza bruta) del verificador de PII, para comparar por equivalencia.
- [ ] 4.2 **GREEN**: implementar el verificador Aho-Corasick en Python puro sobre valores distintos con multiplicidad (suma de multiplicidades presentes por registro, el valor vacío cuenta en todos) en el módulo correspondiente de `pii/`; probar equivalencia O(texto+patrones) contra la versión cuadrática con las semillas de 4.1 en `tests/pii/test_verificador_lineal.py`.
- [ ] 4.3 **RED/GREEN**: ejecutar el verificador sobre la exportación del corpus sintético (PR 3) y sobre el banco completo; probar 0 coincidencias de nombre, DNI y fecha de nacimiento (criterio de éxito de la propuesta); documentar el resultado en `docs/pipeline.md`.
- [ ] 4.4 Cerrar **5.1** de `operacion-segura-y-escalable`: ejecutar `pytest` completo + integraciones PostgreSQL/cola; registrar cobertura de escenarios SDD en `openspec/changes/operacion-segura-y-escalable/tasks.md` (marcar `[x]`).
- [ ] 4.5 Cerrar **5.2** de `operacion-segura-y-escalable`: auditar dataset, logs, manifiestos y diagnósticos contra PII usando el verificador lineal de 4.2; verificar separación de originales/cuarentena; marcar `[x]` en `openspec/changes/operacion-segura-y-escalable/tasks.md`.
- [ ] 4.6 Actualizar `docs/pipeline.md` (diagrama, librerías nuevas: numpy/pyarrow) y proponer las entradas de arquitectura/bitácora en Obsidian para este cambio, con aprobación de un integrante antes de cargarlas (AGENTS.md).

## Trazabilidad tarea → requisito

| Tarea | Requisito de spec |
|---|---|
| 1.1–1.4 | `extraccion-senal-ecg`: extracción vectorial 12+1, calibración por pulsos |
| 1.5 | `corpus-sintetico-clinico` (ADDED): trazos sintéticos con oráculo |
| 2.0, 2.4, 2.5 | `extraccion-senal-ecg`: validación geométrica con degradación explícita; `document-parsing`: campo de señal opcional |
| 2.1–2.3 | `extraccion-senal-ecg`: aislamiento de texto respecto de la señal (storage separado) |
| 3.1, 3.2 | `exportacion-dataset-vinculado`: exportación derivada, vinculación por episodio/ventana 7 días |
| 3.3, 3.4 | `exportacion-dataset-vinculado`: manifiesto de contrato para el consumidor |
| 3.5 | `anonymized-output` (MODIFIED): exportación no muta la base |
| 4.1–4.3 | `exportacion-dataset-vinculado`: cero PII en la exportación |
| 4.4–4.5 | Fase 5 de `operacion-segura-y-escalable` (cierre pendiente) |
