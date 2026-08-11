# Diseño: Ingesta de PDFs clínicos anonimizada

## Enfoque técnico

Se construirá un servicio local *privacy-first* en Python. Un worker lee el PDF desde una fuente autorizada como flujo efímero, lo procesa sólo en memoria y persiste exclusivamente observaciones anonimizadas que superen privacidad y calidad. No hay aplicación ni stack existentes en el repositorio; estas decisiones establecen la base de este cambio, no describen una implementación ya presente.

```text
Fuente autorizada ──flujo efímero──> Worker Python
                                     │
                    clasificar → extraer/adaptar → anonimizar
                                     │                  │
                                     └→ validar PII residual + calidad
                                                        │
                      rechazar: métricas ───────────────┼──> PostgreSQL
                                                        │
                                         aprobadas ─────┘
                                                        ↓
                                      datasets ML versionados
```

## Decisiones de arquitectura

| Decisión | Elección y justificación | Alternativa / descarte |
|---|---|---|
| Runtime | **Python 3.12+**: concentra parsing de PDF, reglas, validación, ORM y evaluación de corpus. | TypeScript: válido para API/UI futura, pero menor ecosistema clínico/documental. |
| Extracción | **PyMuPDF** primario: texto, bloques, coordenadas y tablas en memoria. **pdfplumber** como respaldo selectivo para tablas cuando el corpus demuestre mejora. | Texto plano genérico: no preserva semántica ni permite medir completitud. |
| Diseño | Arquitectura hexagonal: casos de uso orquestan puertos; adaptadores por familia (laboratorio, eco, ECG) implementan extracción. Pipeline explícito para etapas de privacidad/calidad. | Un extractor universal: frágil ante layouts heterogéneos. |
| Persistencia | **PostgreSQL**: tablas relacionales para observaciones aprobadas y JSONB permitido para intercambio/auditoría estructurada. SQLAlchemy + Alembic para acceso y migraciones versionadas. | JSON como única fuente: dificulta consultas, integridad y evolución. |
| Ingesta masiva | Cola con mensajes sin contenido y workers escalables. **Broker pendiente de aprobación**: Redis Streams o RabbitMQ; la decisión depende de volumen, operación y durabilidad requerida. | Pasar PDF/payload a la cola: prohibido por privacidad. |
| Privacidad | Procesamiento en memoria, logs estructurados sin contenido, detector primario más validador residual independiente. Reglas locales serán obligatorias antes de producción. | Servicio cloud: fuera de alcance sin evaluación legal y controles explícitos. |

## Componentes y contratos

Los puertos separan dominio e infraestructura:

```python
class DocumentSource(Protocol):
    def open_stream(self, job_id: str) -> BinaryIO: ...

class FamilyAdapter(Protocol):
    version: str
    def extract(self, pdf: bytes, inventory: FieldInventory) -> ExtractionResult: ...

class PrivacyValidator(Protocol):
    def validate(self, result: ExtractionResult) -> PrivacyResult: ...

class ApprovedObservationStore(Protocol):
    def save(self, approved: ApprovedDocument) -> None: ...
```

`ExtractionResult` contiene candidatos efímeros y, para cada campo del inventario, exactamente un estado: `verified`, `not_present`, `missing`, `ambiguous`, `malformed` o `truncated`. `ApprovedDocument` sólo expone campos `verified`, tipo documental, página/ubicación técnica, versiones de extractor/inventario/esquema y métricas no identificantes. Nunca expone texto fuente, PDF, identificadores ni payloads.

La decisión de documento combina: anonimización, validación residual, inventario completo y política de campos requeridos. Un rechazo persiste únicamente código de motivo, versiones, conteos y métricas agregadas. El job es idempotente mediante un identificador técnico no identificante provisto por la fuente autorizada; no se deriva de PII.

Modelo inicial: `document_run` (estado y versiones), `clinical_observation` (valor tipado, unidad, rango, procedencia y calidad), `dataset_definition` y `dataset_run`. El dataset ML se materializa desde observaciones aprobadas según una definición versionada; no altera la fuente SQL ni exige *target*.

## Calidad, observabilidad y pruebas

Cada adaptador declara un inventario versionado. El evaluador compara el resultado contra un corpus autorizado/anotado y publica cobertura, exactitud de valor/unidad, omisiones, rechazos y PII residual por familia, campo y versión. Ningún adaptador se habilita sin umbrales aprobados; esos umbrales y el corpus son decisiones pendientes, no valores a inventar.

Pruebas: unitarias para parseo, estados y anonimización; integración para adaptador→decisión→PostgreSQL; regresión sobre corpus controlado; pruebas de carga con documentos sintéticos. Los logs y métricas incluyen sólo duración, conteos, versión, tipo y códigos, con revisión automatizada para impedir contenido sensible.

## Archivos previstos

| Ruta | Acción | Finalidad |
|---|---|---|
| `src/clinical_ingestion/domain/` | Crear | Entidades, estados, puertos y políticas. |
| `src/clinical_ingestion/adapters/` | Crear | PyMuPDF, pdfplumber, adaptadores familiares, PostgreSQL y broker. |
| `src/clinical_ingestion/application/` | Crear | Pipeline, casos de uso y derivación ML. |
| `tests/` | Crear | Unitarias, integración y regresión de corpus. |
| `migrations/` | Crear | Esquema SQL versionado. |

## Rollout

1. Acordar fuente autorizada, broker, corpus, inventarios, umbrales y política de retención operacional.
2. Implementar un *spike* local de laboratorio con persistencia deshabilitada; medir corpus.
3. Habilitar persistencia sólo para una versión apta y añadir ecocardiografía/ECG en iteraciones independientes.
4. Materializar datasets ML sólo después de revisar observaciones aprobadas y definiciones versionadas.

## Preguntas abiertas

- [ ] ¿Qué sistema autorizado entrega el flujo de PDF y cómo expira el acceso?
- [ ] ¿Redis Streams o RabbitMQ satisface el volumen, HA y operación esperados?
- [ ] ¿Qué corpus, inventarios y umbrales aprueba el equipo clínico/privacidad?
- [ ] ¿Se requerirá seudonimización longitudinal aprobada?

