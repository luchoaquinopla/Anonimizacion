# Design: Pipeline de extracción y anonimización de PDFs clínicos

## Technical Approach

Pipeline de etapas puras y desacopladas (`ingesta → detectar_tipo → parsear → detectar_pii →
pseudonimizar → emitir`) orquestado por un ejecutor que aísla el fallo **por documento**. Cada etapa es
una función/objeto con contrato tipado; la PII cruda vive **solo en memoria del worker** entre `parsear`
y `pseudonimizar`, y jamás se serializa (ni a cola, ni a log, ni a DLQ, ni a disco temporal). Los parsers
son plugins registrados (patrón Strategy + registro), de modo que un 4to layout es una clase nueva, no un
cambio de core.

## Module Structure

Convención de nombres: archivos, módulos, clases, funciones y variables en **español** (ver
`AGENTS.md`). Se mantienen sin traducir los términos técnicos de facto (`pipeline`, `pii`,
`pepper`, `hash`) y los nombres impuestos por librerías de terceros o convenciones de framework
(`conftest.py`, `app.py` de Celery, `SecretStr` de Pydantic).

```
src/anonimizacion/
├── dominio/           modelos.py (DocumentoParseado, ClavesPaciente, RegistroAnonimizado), tipos_documento.py, errores.py
├── ingesta/           fuente.py (FuenteArtefacto: filesystem/S3), artefacto.py (ArtefactoCrudo: uri+sha256+formato)
├── extraccion/        texto_pymupdf.py (ArtefactoCrudo -> TextoExtraido con bloques+bbox)
├── deteccion/         detector_tipo.py (score por firma de layout), firmas/
├── parseo/            base.py (ParseadorDocumento Protocol), registro.py, ecg_mortara.py, laboratorio_general.py, eco_doppler.py
├── pii/               motor.py (Presidio), reconocedores/dni_ar.py, politica.py (qué campo se descarta/pseudonimiza)
├── pseudonimizacion/  claves.py (HMAC), almacen_pepper.py, resolutor_claves.py, vinculacion.py (ventana ±7 días)
├── salida/            constructor_registro.py, destinos/postgres.py, destinos/parquet.py, cuarentena.py
├── pipeline/          etapas.py, ejecutor.py (aislamiento de fallo), resultado.py
├── trabajadores/      app.py (Celery), tareas.py, politica_reintentos.py
├── observabilidad/    bitacora_segura.py (whitelist + filtro de redacción), metricas.py
└── configuracion/     ajustes.py
tests/fixtures/        PDFs y textos SINTÉTICOS por tipo (nunca reales)
```

## Interfaces / Contracts

```python
class ParseadorDocumento(Protocol):
    tipo_documento: TipoDocumento
    version_esquema: int
    def confianza(self, texto: TextoExtraido) -> float: ...        # 0..1, usado por el detector
    def parsear(self, texto: TextoExtraido) -> DocumentoParseado: ...  # lanza ErrorParseo tipado

@dataclass(frozen=True)
class DocumentoParseado:
    tipo_documento: TipoDocumento
    version_esquema: int
    identidad: IdentidadCruda      # SecretStr: nombre, dni, fecha_nac, ids internos
    fecha_estudio: date
    contenido: ContenidoEcg | ContenidoLaboratorio | ContenidoEco
    adicionales: dict[str, Any]    # remanente estructurado no modelado (escape hatch aditivo)
    fuentes: list[ReferenciaFuente]  # (formato="pdf", uri, sha256) — admite fuentes paralelas
```

`IdentidadCruda` y todo modelo con PII usan `SecretStr` y `__repr__` redactado: imprimirlos nunca revela PII.
`ContenidoEcg` declara `forma_onda: ReferenciaFormaOnda | None = None`; una fuente XML/SCP-ECG futura se
agrega como adaptador adicional que rellena ese campo y suma `fuentes`, **sin cambiar el contrato**
(evolución solo aditiva + `version_esquema`). Eso responde a R1 sin resolverlo.

## Data Flow

```
FuenteArtefacto ──ref(uri+sha256)──> [cola] ──> Worker
                                                 │
   ArtefactoCrudo → TextoExtraido → TipoDocumento → DocumentoParseado → ClavesPaciente → RegistroAnonimizado
                                                 │                              │
                                    (PII solo en memoria)              Postgres + Parquet
                                                 │
                                          fallo → Cuarentena (solo doc_id, código, etapa)
```

Secuencia por documento: `ejecutor.procesar(ref)` → `extraer` → `detectar_tipo` (si score < umbral →
`TIPO_NO_RECONOCIDO`) → `parsear` → `pii.escanear(texto libre + campos)` → `pseudonimizacion.resolver` →
`emitir` → `ack`. Cualquier excepción se envuelve en `ErrorDocumento(id_documento, etapa, codigo)`; **el
mensaje original se descarta** (puede contener texto con PII) y se conserva solo código + offsets.

## Architecture Decisions

### Decision: Pseudonimización con HMAC y doble clave de identidad
**Choice**: `id_paciente = HMAC-SHA256(key=pepper, msg=canonical(dni))[:16 bytes]` en hex. Canonicalización:
sin puntos/espacios, sin ceros a izquierda. El ECG **no trae DNI**, por lo que se emite además
`id_alt_paciente = HMAC(key=pepper, "alt|" + nombre_normalizado + "|" + fecha_nac)`. El laboratorio (trae
nombre + DNI + fecha de nacimiento) actúa de **puente**: emite ambos y permite mapear `id_alt_paciente →
id_paciente` en una tabla de resolución. Si no hay ninguna clave resoluble → `CLAVE_PII_NO_RESUELTA`,
a cuarentena.
**Alternatives**: hash simple (SHA-256 del DNI) — rechazado: espacio de DNI es enumerable, un hash sin
clave es reversible por fuerza bruta en minutos. Cifrado reversible — rechazado: crea un camino de
re-identificación que el protocolo no necesita.
**Rationale**: HMAC con pepper secreto es determinístico (permite linkage) y no invertible sin la clave.
`version_clave` se persiste en cada registro para permitir rotación.

### Decision: Almacenamiento del pepper
**Choice**: secreto único por entorno en un almacén separado del dataset (variable de entorno inyectada
desde Vault/KMS, o archivo cifrado con permisos 0400 en on-prem), cargado en memoria del worker al arrancar,
nunca en el repo, nunca en el mismo servidor de datos, nunca logueado.
**Alternatives**: salt por paciente en tabla — rechazado: la tabla salt↔paciente ES el mapa de
re-identificación, exactamente lo que se busca evitar.

### Decision: Ventana de ±7 días — clustering por ancla, no encadenado
**Choice**: por `id_paciente`, ordenar documentos por `fecha_estudio`; el primero abre un episodio y se
absorben los documentos con `|fecha - fecha_ancla| ≤ 7`; el primero fuera de rango abre un episodio nuevo.
`id_episodio = HMAC(pepper, id_paciente + "|" + fecha_ancla)`. Determinístico y recomputable (batch, no
mutación incremental); desempate por `(fecha, tipo_documento, id_documento)`.
**Alternatives**: encadenado transitivo (unir si algún par está a ≤7 días) — rechazado: produce deriva
(día 0 y día 30 quedarían en el mismo episodio vía saltos), inaceptable clínicamente.

### Decision: Aislamiento de fallo y política de reintentos
**Choice**: fallo por documento nunca aborta el lote (R5). Reintento **solo** para errores transitorios
(IO, storage, DB): 3 intentos, backoff exponencial 5s/30s/180s. Errores determinísticos
(`TIPO_NO_RECONOCIDO`, `PARSEO_INCOMPLETO`, `CLAVE_PII_NO_RESUELTA`) **no se reintentan**: van directo a
cuarentena para revisión y reproceso manual tras corregir el parser.
**Rationale**: reintentar un parse determinístico solo quema workers y multiplica la exposición.

### Decision: Sin PII en cola, logs ni DLQ (R4)
**Choice**: cuatro barreras. (1) El mensaje de cola transporta **solo** `{id_documento, uri, sha256}` —
nunca contenido; por construcción la DLQ no puede contener PII. (2) `bitacora_segura` serializa
únicamente campos de una whitelist (`id_documento`, `tipo_documento`, `etapa`, `codigo`, `duracion_ms`);
un campo no declarado se descarta, no se loguea "por las dudas". (3) Filtro de redacción como segunda
defensa (regex DNI + spans detectados por Presidio) sobre cualquier string que llegue al logger.
(4) `SecretStr` + `__repr__` redactado, y captura de excepciones en el borde de cada etapa que
**reemplaza** el mensaje original por un código.
**Alternatives**: confiar solo en el filtro de redacción — rechazado: es una lista negra, y una lista negra
falla en silencio justo con el dato que no previste.

### Decision (Q1): Storage híbrido — Postgres como sistema de registro + Parquet como capa de entrenamiento
**Choice**: PostgreSQL normalizado para linkage, catálogo y trazabilidad; export a Parquet columnar
particionado (`tipo_documento/año`) como dataset de consumo del pipeline de DL. Las tablas clave:
`vinculo_paciente(id_alt_paciente, id_paciente)`, `episodio`, `medicion_ecg` (ancha: PR/QRS/QT/QTc/ejes —
esquema fijo), `resultado_laboratorio` (**larga/EAV**: `id_episodio, analito, seccion, valor_num,
valor_texto, unidad, ref_min, ref_max`), `medicion_eco` (ancha) + `texto_seccion_eco` (una fila por
sección de texto libre, ya depurada de PII). `JSONB` solo para `adicionales`, nunca como camino de acceso
primario.

| Opción | Tradeoff | Decisión |
|---|---|---|
| SQL puro, lab en tabla ancha (una columna por prueba) | Sparse extremo y DDL nuevo por cada analito | Rechazado |
| SQL con lab en formato largo + export Parquet | Esquema estable ante paneles variables; pivot a ancho en feature-building; lecturas columnares baratas | **Elegido** |
| NoSQL documental (Mongo) | Absorbe forma variable, pero sin validación de esquema, joins de linkage en aplicación y lectura de 100k docs lenta para entrenamiento | Rechazado |

**Rationale**: la forma real del dato es mixta, no "documental": ECG y eco son esquemas fijos, y lo único
variable es *qué analitos están presentes* — un problema clásico de tabla larga, no de documentos sin
esquema. 100k registros es un volumen trivial para Postgres, que además impone integridad referencial al
linkage (el punto más delicado). Parquet cubre lo que Postgres hace mal: lecturas columnares repetidas
por época de entrenamiento.

### Decision (Q2): Retención cifrada de los PDFs originales, no borrado inmediato
**Choice**: zona segregada de almacenamiento (bucket/volumen aparte del dataset), cifrada en reposo
(SSE-KMS en object storage, o LUKS/age en on-prem), acceso **solo lectura** para el rol worker, con
retención **por evento**: se conservan hasta que el dataset derivado esté congelado y validado por el
responsable del protocolo, con tope duro al cierre del estudio y procedimiento de destrucción documentado.
Ningún PDF se copia fuera de esa zona.
**Alternatives**: borrado inmediato tras procesar — rechazado: el plan de rollback declara al PDF fuente
de verdad; sin él, un bug de parser detectado a los 60k documentos es irrecuperable y el estudio pierde
reproducibilidad, que es un requisito de la investigación.
**Rationale**: minimización de datos (25.326) se cumple restringiendo *acceso y superficie*, no
destruyendo la única fuente reprocesable a mitad del proyecto.

### Decision (Q3): El nombre del médico se pseudonimiza en namespace propio
**Choice**: `id_medico = HMAC(pepper, "medico|" + nombre_normalizado)`; la matrícula recibe el mismo
tratamiento (es identificador directo). Los bloques de firma en texto libre se depuran.
**Alternatives**: retenerlo en claro como metadato profesional — rechazado; borrarlo por completo —
rechazado.
**Rationale**: no aporta señal predictiva al modelo, así que retenerlo en claro es riesgo sin beneficio, y
además **es cuasi-identificador del paciente**: médico poco frecuente + fecha + institución reduce
drásticamente el conjunto de pacientes posibles. Pseudonimizarlo conserva lo único útil (agrupar por
operador para analizar variabilidad inter-observador) sin exponer nombres.

### Decision: La detección de PII corre también sobre texto libre
**Choice**: `pii.motor` se aplica a las secciones narrativas del eco (motilidad, conclusiones) y a
cualquier `adicionales` textual, no solo a los campos del header.
**Rationale**: en la práctica el nombre del paciente reaparece dentro de la conclusión dictada; anonimizar
solo el header es una falsa sensación de seguridad (R2).

## File Changes

| Archivo | Acción | Descripción |
|---|---|---|
| `pyproject.toml` | Create | Stack: pymupdf, presidio-analyzer, spacy + es_core_news_lg, pydantic, celery, redis, sqlalchemy, pyarrow, pytest |
| `src/anonimizacion/dominio/*` | Create | Modelos tipados, TipoDocumento, jerarquía de errores |
| `src/anonimizacion/extraccion/texto_pymupdf.py` | Create | PDF → bloques de texto con bbox |
| `src/anonimizacion/deteccion/detector_tipo.py` | Create | Score por firma de layout + umbral |
| `src/anonimizacion/parseo/{base,registro,ecg_mortara,laboratorio_general,eco_doppler}.py` | Create | Protocol + registro + 3 parsers |
| `src/anonimizacion/pii/{motor,reconocedores/dni_ar,politica}.py` | Create | Presidio + recognizer DNI + política por campo |
| `src/anonimizacion/pseudonimizacion/{claves,almacen_pepper,resolutor_claves,vinculacion}.py` | Create | HMAC, pepper, doble clave, episodios ±7d |
| `src/anonimizacion/salida/*` | Create | Builder + destinos Postgres/Parquet + cuarentena |
| `src/anonimizacion/pipeline/ejecutor.py` | Create | Orquestación y aislamiento de fallo |
| `src/anonimizacion/trabajadores/*` | Create | Celery app, tarea por documento, política de reintentos |
| `src/anonimizacion/observabilidad/bitacora_segura.py` | Create | Logger de whitelist + filtro de redacción |
| `openspec/config.yaml` | Modify | `tdd: true`, `test_command: "pytest"` |

## Testing Strategy

| Capa | Qué testear | Enfoque |
|---|---|---|
| Unit | Canonicalización de DNI, HMAC determinístico, clustering ±7d (bordes: exactamente 7, 8 días, empates) | pytest, tablas de casos |
| Unit | Cada parser contra fixture sintética; tolerancia a `PID / NAME MISMATCH`; lab multipágina con header repetido | fixtures sintéticas versionadas |
| Unit | `bitacora_segura`: inyectar registro con PII y afirmar que la salida no la contiene | property test con generador de DNI/nombres |
| Integration | Ejecutor: 1 documento roto en un lote de N no aborta el lote y deja rastro en cuarentena | pipeline en memoria |
| Integration | Ningún registro emitido contiene nombre/DNI/fecha de nacimiento | escaneo del output con el propio motor de PII |
| E2E | ECG + Lab + Eco sintéticos del mismo paciente a ≤7 días → mismo `id_paciente` y mismo `id_episodio` | corrida completa con destinos temporales |
| Seguridad | Ninguna llamada de red durante el procesamiento | socket bloqueado en la suite |

## Migration / Rollout

No hay migración: repositorio greenfield. Rollout por fases: (1) núcleo + parser de laboratorio (el más
rico en features) validado a mano contra muestras reales fuera del repo; (2) ECG y eco; (3) activación de
workers/cola sobre el corpus completo. El linkage se recomputa en batch, por lo que reprocesar es idempotente.

## Open Questions

- [ ] R1 (señal cruda de ECG): decisión de negocio fuera de este repo. El diseño la absorbe vía
      `sources[]` + `EcgPayload.waveform` opcional, sin rediseño del pipeline.
- [ ] Infraestructura concreta del pepper (Vault vs KMS vs archivo cifrado on-prem) — depende del entorno
      del instituto.
- [ ] Umbral de confianza del detector de tipo y de Presidio: a calibrar contra el corpus real antes de
      correr a escala.
