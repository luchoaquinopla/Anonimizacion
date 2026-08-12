# Arquitectura hexagonal en la ingesta clínica

Esta guía explica cómo mantener reglas clínicas, privacidad y calidad independientes de PyMuPDF, PostgreSQL o una cola. El resultado será un servicio modular: **no** un conjunto de microservicios.

## Camino rápido

1. El adaptador de entrada recibe una referencia técnica desde la fuente autorizada o cola.
2. El caso de uso orquesta extracción, anonimización y calidad.
3. Sólo si el resultado es aprobado, un adaptador de salida lo guarda en PostgreSQL.

```text
Fuente autorizada / cola → adaptador de entrada → caso de uso
→ extractor de familia → privacidad y calidad → store PostgreSQL
```

El PDF y el texto crudo viven sólo durante el procesamiento; no van a la cola, logs ni base de datos.

## Conceptos

| Término | Qué es en este proyecto |
|---|---|
| Dominio | Reglas clínicas y de calidad: estados de campo, aprobación y datos permitidos. No conoce librerías ni base de datos. |
| Puerto | Interfaz que expresa una necesidad del núcleo. Ejemplo: “obtener un documento autorizado” o “guardar observaciones aprobadas”. |
| Adaptador | Implementación concreta de un puerto. Ejemplo: PyMuPDF extrae un PDF; SQLAlchemy escribe en PostgreSQL. |
| Caso de uso | Coordina la secuencia: procesar un trabajo, extraer, anonimizar, validar y aprobar/rechazar. |

### Direcciones

- **Entrada / driving (inbound):** algo inicia el sistema. Una cola, CLI o HTTP llama al puerto/caso de uso `ProcessDocument`.
- **Salida / driven (outbound):** el núcleo necesita algo externo. Invoca puertos como `DocumentSource`, `FamilyAdapter` y `ApprovedObservationStore`; los adaptadores concretos responden.

La regla es que las dependencias apuntan **hacia adentro**: adaptadores e infraestructura importan aplicación/dominio; dominio no importa PyMuPDF, SQLAlchemy, Redis ni HTTP. Así una librería se reemplaza sin alterar reglas de privacidad o calidad.

## Puertos y adaptadores aplicados

```text
Puerto de salida: FamilyAdapter.extract(documento, inventario)
Adaptador:       LaboratoryPyMuPdfAdapter
Adaptador:       EchocardiographyPyMuPdfAdapter
Adaptador:       EcgPyMuPdfAdapter

Puerto de salida: ApprovedObservationStore.save(documento_aprobado)
Adaptador:       PostgresApprovedObservationStore
```

Los nombres son conceptuales, no archivos existentes. Cada adaptador familiar conoce la estructura de su informe; el caso de uso conserva la misma política de anonimización, calidad y persistencia para todos.

## Relación con Strategy

Se parecen porque ambos separan el “qué” del “cómo”, pero resuelven problemas distintos:

| Patrón | Propósito |
|---|---|
| Puertos y adaptadores | Define límites entre el núcleo y el exterior. Decide quién puede depender de quién. |
| Strategy | Selecciona un algoritmo intercambiable dentro de un contexto. |

`FamilyAdapter` es un puerto arquitectónico: permite conectar implementaciones externas al caso de uso. Dentro de, por ejemplo, `LaboratoryPyMuPdfAdapter`, puede usarse Strategy para escoger el algoritmo de tabla según plantilla: `FixedColumnsStrategy` o `CoordinateBasedStrategy`. El caso de uso no conoce ninguno de esos algoritmos. No hay que llamar “Strategy” a cada puerto: eso borra el límite arquitectónico que necesitamos proteger.

## Estructura propuesta

```text
src/clinical_ingestion/
├── domain/                         # entidades, value objects, reglas y estados clínicos puros
├── application/
│   ├── ports/
│   │   ├── inbound/                 # contratos que exponen casos de uso, ej. ProcessDocument
│   │   └── outbound/                # contratos que requiere el núcleo, ej. Store y FamilyAdapter
│   └── use_cases/                   # orquestación de ingesta, aprobación y datasets
├── adapters/
│   ├── inbound/                     # consumidores de cola, CLI o controladores HTTP futuros
│   └── outbound/                    # PyMuPDF/pdfplumber, fuente autorizada y PostgreSQL
├── bootstrap/                       # configuración y composición: conecta puertos con adaptadores
tests/                               # pruebas unitarias, integración y regresión del corpus
```

`bootstrap` es el único lugar que debe conocer qué adaptador concreto se usa en cada entorno. Una prueba puede conectar un adaptador en memoria; producción conecta PostgreSQL y el extractor aprobado.

## Checklist para colaborar

- [ ] Si escribís una regla de privacidad o calidad, ubicála en dominio o caso de uso, no en un adaptador.
- [ ] Si agregás una dependencia externa, creá o implementá el puerto de salida apropiado.
- [ ] Si llega una nueva plantilla, agregá/extendé el adaptador de su familia y medilo contra el corpus.
- [ ] Si necesitás cambiar algoritmo de parsing dentro de una familia, evaluá Strategy dentro del adaptador.
