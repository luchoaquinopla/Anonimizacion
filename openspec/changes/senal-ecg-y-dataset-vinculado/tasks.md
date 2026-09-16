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

- [x] 2.0 **Alineación de specs**: actualizar `openspec/changes/senal-ecg-y-dataset-vinculado/specs/extraccion-senal-ecg/spec.md` y `specs/document-parsing/spec.md` para que el nombre del campo en `campos_no_extraidos` sea `ecg.senal` (consistente con el diseño y con `dominio/referencias.py`), no `senal` suelto.
- [x] 2.1 **RED/GREEN**: crear `src/anonimizacion/salida/codec_senal.py` (codificación `int16` µV little-endian + zlib para la señal, `packbits` + zlib para la máscara) con ida y vuelta probada en `tests/salida/test_codec_senal.py`.
- [x] 2.2 **RED/GREEN**: crear migración `migrations/versions/0013_senal_ecg.py`: tabla `senal_ecg` (PK = FK `id_estudio`, `ON DELETE CASCADE`, `SET STORAGE EXTERNAL` sólo en Postgres); probar upgrade/downgrade en `tests/salida/test_migraciones.py`.
- [x] 2.3 **RED/GREEN**: extender `src/anonimizacion/salida/modelos_orm.py` con el modelo ORM de `senal_ecg`; extender `parseo/ecg_mortara.py` (`ContenidoEcg.senal: SenalEcg | None = None` -- desviación de ubicación respecto del texto de la tarea, ver apply-progress) y `salida/modelos_salida.py` (`ContenidoEcgSalida.senal`); probar serialización en `tests/parseo/test_ecg_mortara.py` y `tests/salida/test_modelos_orm.py`/`tests/salida/destinos/test_postgres.py`.
- [x] 2.4 **RED/GREEN**: modificar `parseo/ecg_mortara.py` para invocar `construir_senal` sobre los trazos capturados (vía el registro de 1.3) y modificar `reconciliacion/ecg_mortara.py` para agregar `ecg.senal` a `campos_no_extraidos` cuando `senal=None`, sin cuarentena por ese motivo; probar en `tests/parseo/test_ecg_mortara.py` y `tests/reconciliacion/test_ecg_mortara.py` los 3 escenarios de la spec (señal válida, señal inválida, advertencia de equipo tolerada).
- [x] 2.5 **RED/GREEN**: modificar `dominio/referencias.py` para registrar `ecg.senal` como campo no extraído válido; modificar `pipeline/ejecutor.py` para inyectar el capturador de trazos (vía `registro_trazos.py`) al abrir el PDF una sola vez, y para persistir `estudio` + `medicion_ecg` + `senal_ecg` en una sola transacción; modificar `salida/constructor_registro.py` y `salida/destinos/postgres.py` para escribir la señal; probar idempotencia por `clave_documento` en `tests/salida/destinos/test_postgres.py` (reintento no duplica `senal_ecg`; incluye atomicidad estudio+señal contra Postgres real).
- [x] 2.6 **REFACTOR**: revisar que `pipeline/ejecutor.py` no llame `detectar_tipo` más de dos veces por documento (decisión #1 del diseño) y que los fakes de tests existentes sigan pasando sin cambios de contrato en `extraer_texto_de_flujo` para laboratorio/eco.

## Phase 3: Exportación (PR 3, ~350 líneas)

Depende de PR 2 (lee `senal_ecg`, `estudio` y las tablas de laboratorio/eco ya existentes). Rollback boundary: la exportación sólo lee de Postgres — revertir el PR no requiere migración ni afecta datos persistidos.

- [x] 3.1 **RED**: crear `tests/salida/test_exportacion.py` fijando el esquema exacto (lista blanca de columnas) de cada Parquet (`episodios`, `ecg`, `laboratorio`, `eco`) contra la spec de cero PII; confirmar que `clave_documento`, `corrida_id`, `id_medico*` y el texto libre del eco quedan afuera.
- [x] 3.2 **GREEN**: crear `src/anonimizacion/salida/exportacion.py`: streaming en una transacción `REPEATABLE READ` (Postgres; SQLite usa su nivel por defecto), paginación por CLAVE (`id_episodio > último`, no OFFSET, lotes de 256), un `ParquetWriter` por tabla con un row group por lote, escritura en `<archivo>.tmp` con rename atómico. **Desviación de diseño (menor, documentada)**: la vinculación por `patient_id` + ventana de 7 días YA está resuelta al momento de escribir cada `estudio` (`estudio.id_episodio`, ver `pseudonimizacion/vinculacion.py` + `destinos/postgres.py::escribir_episodio`) -- exportar sólo AGRUPA por esa clave ya persistida, no reimplementa el clustering. Campos faltantes marcados vía `episodios.{tiene_ecg,tiene_laboratorio,tiene_eco,completo}`, sin descartar episodios incompletos.
- [x] 3.3 **RED/GREEN**: generar `manifiesto.json` (versión de esquema de exportación, 500 Hz, unidad µV, orden de las 12 derivaciones + tira de ritmo, ventanas por columna, `version_formato`, ventana de vinculación, conteos, sha256 de cada archivo); probado en `tests/salida/test_exportacion.py`.
- [x] 3.4 **RED/GREEN**: constantes de contrato (`EsquemaPdf` de `modelo_hvi`, medidas a mano y copiadas como LITERALES, sin importar `modelo_hvi`) y test de contrato: decimar ×2 la señal exportada da (12, 2500), 619 muestras por tramo coincidiendo con `EsquemaPdf`, V1 completa (2500) por ser la tira de ritmo (`tests/salida/test_contrato_modelo_hvi.py`).
- [x] 3.5 **RED/GREEN**: subcomando `exportar` en `cli.py` (`--salida`, `--tamano-pagina`); probado en `tests/test_cli.py` (wiring con mock + extremo real contra SQLite de archivo verificando no-mutación y archivos producidos). No usa `diagnosticar` (no procesa PDFs ni requiere `--entrada`).
- [x] 3.6 **Dependencias**: `numpy>=1.26`/`pyarrow>=15` agregadas como dependencias BASE en `pyproject.toml` (no extra opcional). Evidencia para versionar `uv.lock`: no está en `.gitignore`, sin historial previo en `git log --all -- uv.lock`, y `scripts/instalar.ps1` no usa `uv` (no depende del lockfile) -- corresponde versionarlo igual, por ser la única fuente de resolución reproducible del repo. `uv lock` ejecutado y commiteado junto con el cambio de `pyproject.toml`.

## Phase 4: Verificador PII lineal + cierre fase 5 de `operacion-segura-y-escalable` (PR 4, ~150 líneas)

Depende de PR 3 (audita la exportación). Rollback boundary: el verificador es una herramienta de auditoría, sin efecto en datos; revertir el PR no afecta el pipeline productivo.

- [x] 4.1 **RED**: crear `tests/fixtures/verificador_pii.py` con semillas de prueba y una versión de referencia cuadrática (fuerza bruta) del verificador de PII, para comparar por equivalencia.
- [x] 4.2 **GREEN**: implementar el verificador Aho-Corasick en Python puro sobre valores distintos con multiplicidad (suma de multiplicidades presentes por registro, el valor vacío cuenta en todos) en el módulo correspondiente de `pii/`; probar equivalencia O(texto+patrones) contra la versión cuadrática con las semillas de 4.1 en `tests/pii/test_verificador_lineal.py`.
- [x] 4.3 **RED/GREEN**: ejecutar el verificador sobre la exportación del corpus sintético (PR 3) y sobre el banco completo; probar 0 coincidencias de nombre, DNI y fecha de nacimiento (criterio de éxito de la propuesta); documentar el resultado en `docs/pipeline.md`.
  - Auditoría de punta a punta agregada en `tests/pii/test_auditoria_exportacion_sin_pii.py`: corpus sintético → pipeline real → `exportar_dataset` → verificador lineal sobre los 4 Parquet + manifiesto, 0 coincidencias; falsabilidad demostrada con un segundo test que inyecta PII a propósito y confirma detección. Resultado documentado en `docs/pipeline.md` (sección "Señal de ECG y dataset vinculado exportado").
  - Encontró y corrigió un defecto real en `salida/exportacion.py`: `ESQUEMA_ECG` usaba `pa.list_(tipo, N)` (tamaño fijo) para `muestras_uv`/`mascara`, que pyarrow 25.0.1 no puede releer desde Parquet cuando TODAS las filas de una página no tienen señal (`ArrowInvalid`) — caso real, no hipotético. Cambiado a lista de tamaño variable; el invariante de largo sigue garantizado por `SenalEcg.__post_init__`.
- [x] 4.4 Cerrar **5.1** de `operacion-segura-y-escalable`: ejecutar `pytest` completo + integraciones PostgreSQL/cola; registrar cobertura de escenarios SDD en `openspec/changes/operacion-segura-y-escalable/tasks.md` (marcar `[x]`).
- [x] 4.5 Cerrar **5.2** de `operacion-segura-y-escalable`: auditar dataset, logs, manifiestos y diagnósticos contra PII usando el verificador lineal de 4.2; verificar separación de originales/cuarentena; marcar `[x]` en `openspec/changes/operacion-segura-y-escalable/tasks.md`.
  - Dataset+manifiesto: `tests/pii/test_auditoria_exportacion_sin_pii.py` (nuevo, de punta a punta). Logs/bitácora: ya cubierto por `tests/observabilidad/test_bitacora_segura.py` (incluye test de propiedad `test_property_pii_inyectada_nunca_aparece_en_la_salida`). Registros/salida: `tests/integracion/test_salida_sin_pii.py`. Diagnósticos (`diagnostico.py`) no tienen superficie de PII de paciente (sólo estado de migraciones/config/cola) -- sin hallazgos. Separación originales/cuarentena: cubierta por los tests existentes de `ingesta/` y `cuarentena` (sin cambios en esta ronda).
- [x] 4.6 Actualizar `docs/pipeline.md` (diagrama, librerías nuevas: numpy/pyarrow) y proponer las entradas de arquitectura/bitácora en Obsidian para este cambio, con aprobación de un integrante antes de cargarlas (AGENTS.md).
  - `docs/pipeline.md` actualizado: diagrama con la rama de trazos/señal/exportación, sección nueva "Señal de ECG y dataset vinculado exportado", subsección "numpy + PyArrow", y corrección de la sección de PostgreSQL que decía (falsamente, a esta altura del repo) que Parquet había sido eliminado sin reintroducirse.
  - Entradas de arquitectura/bitácora en Obsidian: PENDIENTE -- requiere aprobación de un integrante antes de cargarlas (AGENTS.md); no se propone contenido en este cierre porque excede el alcance de este agente (no tiene acceso al vault).

## Entrega 2b: corrección de adicionales no persistidos (PR aparte, antes de PR3)

Corrección post-entrega-2 (PR #46 ya mergeado): `_escribir_laboratorio` y `_escribir_eco`
(`salida/destinos/postgres.py`) nunca leían `registro.adicionales`; sólo `_escribir_ecg`
lo persistía, en `medicion_ecg.adicionales`. Se perdían en silencio edad/origen
(laboratorio) y edad/peso/altura/superficie_corporal (eco), contradiciendo la decisión
de comité 2026-09-07. Rama `fix/adicionales-de-laboratorio-y-eco` desde la integradora
`feat/senal-ecg-y-dataset-vinculado` (head: migración `0013_senal_ecg`). Bloquea PR3
(exportación), que exige leer estos campos ya persistidos.

- [x] 2b.1 **Auditoría de lectores**: `rg` de `MedicionEcg.adicionales`/`MedicionEcg(` en
  `src/` y `tests/` -- ningún panel, embudo, reporte ni script de producción lo lee (sólo
  el escritor de `postgres.py` y los tests de `tests/salida/`). Decisión: ELIMINAR la
  columna en vez de duplicarla, migrando su contenido a `estudio.adicionales`.
- [x] 2b.2 **RED/GREEN**: migración `migrations/versions/0014_adicionales_en_estudio.py`
  (`down_revision = 0013_senal_ecg`, única cabecera): agrega `estudio.adicionales` JSON
  portable nullable, copia `medicion_ecg.adicionales` -> `estudio.adicionales` para filas
  ya escritas (bases de prueba de la entrega 2), y elimina `medicion_ecg.adicionales`.
  Downgrade simétrico. Probado upgrade/downgrade contra SQLite
  (`tests/salida/test_migraciones.py`) y de punta a punta + copia de datos contra
  Postgres real (`@pytest.mark.postgres`).
- [x] 2b.3 **GREEN**: `salida/modelos_orm.py` agrega `Estudio.adicionales`, elimina
  `MedicionEcg.adicionales`. `salida/destinos/postgres.py::_insertar` persiste
  `registro.adicionales` en `estudio.adicionales` para los 3 tipos; `_escribir_eco` sigue
  guardando sólo las medidas no pivoteadas en `medicion_eco.adicionales` (campo distinto,
  documentado en el docstring de `MedicionEco`).
- [x] 2b.4 **RED/GREEN**: `tests/salida/destinos/test_postgres.py` -- ida y vuelta de
  `estudio.adicionales` para los 3 tipos con valores literales (oráculo escrito a mano);
  test parametrizado que recorre laboratorio/ECG/eco exigiendo `estudio.adicionales`
  poblado; test de que `_CLAVES_PERSONAL` (médico derivante/solicitante, técnico) nunca
  llega a `estudio.adicionales`, contra Postgres real (`@pytest.mark.postgres`).
- [x] 2b.5 **Specs**: agregado requisito `ADDED` "Persistencia de campos adicionales de
  header" en `specs/anonymized-output/spec.md`, con escenarios de los 3 tipos y de
  ausencia de campos personales.
- [x] 2b.6 **Verificación**: `pytest -q` (978 passed, 1 skipped), `pytest -q -m postgres`
  (21 passed), `ruff check .` (All checks passed).
- [x] 2b.7 **Correcciones de revisión adversarial**: test de PII vacuo (`medico_solicitante`/
  `tecnico` nunca aparecían en el input, eco nunca se ejercitaba) reemplazado por uno
  parametrizado con las 3 claves de `_CLAVES_PERSONAL` y los 3 tipos, con demostración
  manual de que falla si se rompe `_adicionales_sin_personal`; corrección de la atribución
  causal de por qué se migró la base compartida (era `diagnostico.py::_diagnosticar_migraciones`,
  no el fixture de `test_cli.py`); test de downgrade con los 3 tipos poblados contra
  Postgres real efímero; tests repetidos parametrizados para no crecer el diff; comentario
  de la migración 0014 corregido. Verificación final: `pytest -q -m "not postgres"`
  (974 passed, 1 skipped), `pytest -q -m postgres` (23 passed, sin tocar la base
  compartida), `ruff check .` (limpio).

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
| 2b.1–2b.7 | `anonymized-output` (ADDED): persistencia de adicionales de header para los 3 tipos |
