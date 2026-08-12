# Diseño: Ingesta de PDFs clínicos anonimizada

## Decisión

Se construirá un servicio local *privacy-first* en Python 3.12+. Leerá cada PDF desde una fuente autorizada como flujo efímero, procesará en memoria y persistirá sólo observaciones anonimizadas que superen controles de privacidad y calidad. No hay implementación existente: este documento define la base del cambio.

```text
Fuente autorizada / cola (sólo referencia técnica)
  → caso de uso de ingesta → extractor por familia
  → anonimización y calidad → PostgreSQL (sólo datos aprobados)
  → datasets ML derivados y versionados
```

La guía para colaboradores y el árbol completo propuesto están en [Arquitectura hexagonal](../../../docs/architecture/hexagonal.md). Es un servicio modular, no una propuesta de microservicios.

## Decisiones técnicas

| Área | Elección y por qué |
|---|---|
| Runtime | **Python 3.12+** concentra extracción documental, reglas, validación, ORM y evaluación del corpus. TypeScript puede servir para una API/UI futura, pero no será el motor de extracción. |
| Extracción | **PyMuPDF** será primario para texto, bloques, coordenadas y tablas en memoria. **pdfplumber** será respaldo selectivo sólo si el corpus demuestra una mejora en tablas. |
| Arquitectura | Hexagonal: los casos de uso dependen de puertos y la infraestructura los implementa con adaptadores. Se usarán adaptadores por familia (laboratorio, ecocardiografía, ECG), no un extractor universal. |
| Persistencia | **PostgreSQL** para observaciones aprobadas; JSONB permitido para intercambio/auditoría estructurada. SQLAlchemy y Alembic versionarán acceso y migraciones. |
| Ingesta masiva | Cola y workers escalables; los mensajes no contienen PDF ni payload clínico. Broker pendiente: Redis Streams o RabbitMQ, según volumen, disponibilidad y operación. |
| Privacidad | Memoria efímera, logs sin contenido, detector primario y validador residual independiente. Un servicio cloud queda fuera de alcance sin evaluación legal y controles explícitos. |

## Contratos y flujo

Los puertos expresan necesidades del núcleo, no tecnologías concretas:

- `DocumentSource`: abre el flujo autorizado del documento.
- `FamilyAdapter`: clasifica y extrae una familia documental con su inventario de campos.
- `PrivacyValidator`: comprueba anonimización y PII residual.
- `ApprovedObservationStore`: guarda exclusivamente un documento aprobado.

`ExtractionResult` es efímero y asigna a cada campo un único estado: `verified`, `not_present`, `missing`, `ambiguous`, `malformed` o `truncated`. `ApprovedDocument` sólo contiene campos `verified`, tipo documental, página/ubicación técnica, versiones y métricas no identificantes. Nunca expone PDF, texto fuente, identificadores ni payloads.

La decisión de aprobación combina anonimización, validación residual, inventario completo y política de campos requeridos. Un rechazo persiste sólo códigos de motivo, versiones, conteos y métricas agregadas. El trabajo es idempotente mediante un identificador técnico no identificante entregado por la fuente autorizada.

Modelo inicial: `document_run` (estado y versiones), `clinical_observation` (valor tipado, unidad, rango, procedencia y calidad), `dataset_definition` y `dataset_run`. Un dataset ML se materializa desde observaciones aprobadas con una definición versionada; no altera la fuente SQL ni requiere definir todavía un *target*.

## Calidad y pruebas

Cada adaptador declara un inventario versionado. El evaluador compara resultados con un corpus autorizado y anotado, y publica cobertura, exactitud de valor/unidad, omisiones, rechazos y PII residual por familia, campo y versión. No se habilita un adaptador sin umbrales aprobados; corpus y umbrales siguen pendientes.

Habrá pruebas unitarias de parseo, estados y anonimización; integraciones de adaptador a decisión y PostgreSQL; regresión sobre corpus controlado; y carga con documentos sintéticos. Logs y métricas incluirán sólo duración, conteos, versión, tipo y códigos.

## Rutas previstas

```text
src/clinical_ingestion/
  domain/                     # reglas y tipos clínicos puros
  application/                # casos de uso y puertos
  adapters/inbound/           # cola, CLI o HTTP futuros
  adapters/outbound/          # PDF, PostgreSQL y fuente autorizada
  bootstrap/                  # composición de dependencias
tests/                        # unitarias, integración y corpus autorizado
migrations/                   # esquema SQL versionado
```

## Rollout y preguntas abiertas

1. Acordar fuente autorizada, broker, corpus, inventarios, umbrales y retención operacional.
2. Crear un *spike* local de laboratorio sin persistencia y medir el corpus.
3. Habilitar persistencia sólo para una versión apta; añadir ecocardiografía y ECG en iteraciones separadas.
4. Materializar datasets ML después de revisar observaciones y definiciones aprobadas.

- [ ] Definir sistema que entrega el flujo y expiración de acceso.
- [ ] Elegir broker tras conocer volumen, HA y operación.
- [ ] Aprobar corpus, inventarios y umbrales con clínica/privacidad.
- [ ] Resolver si se requerirá seudonimización longitudinal.
