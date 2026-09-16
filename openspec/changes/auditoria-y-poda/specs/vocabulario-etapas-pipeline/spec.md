# Especificación: vocabulario único de etapas

Capacidad nueva (Entrega 2). Unifica los nombres de etapa que hoy divergen entre
`dominio/errores.py:16-36` (`EtapaDocumento`), `pipeline/etapas.py:23-37` (`Etapa`) y
`web/embudo_corrida.py:59-68` (`ETAPAS_EMBUDO`), sin acoplar dominio a pipeline.
Evidencia: `auditoria/consolidado-2026-09` (obs #1338), `proposal.md` sección "Entrega 2"
y su "Corrección al análisis original".

## Requisito 1: un enum como fuente de verdad de los nombres de etapa

El sistema **MUST** tener un único enum que enumere todos los nombres de etapa válidos
del pipeline (unión de los miembros hoy dispersos en `EtapaDocumento`, `Etapa` y
`ETAPAS_EMBUDO`).

#### Escenario: los nombres de las tres fuentes actuales son miembros del enum
- **Given** el enum unificado
- **When** se listan sus miembros
- **Then** incluye `DESPACHO` (de `EtapaDocumento`), `COORDINACION` (de `Etapa`) y
  `deteccion` / `deteccion_pii` (ausentes hoy en `ETAPAS_EMBUDO`)

## Requisito 2: `ErrorDocumento.etapa` sigue aceptando `str`

`ErrorDocumento.etapa` **MUST** seguir aceptando `str | EtapaDocumento` como hoy
(`errores.py:243`). El sistema **MUST NOT** endurecer ese campo a un tipo enum estricto:
los `_ETAPA = "parseo"` planos en `parseo/registro.py:18`, `parseo/ecg_mortara.py:87`,
`parseo/laboratorio_general.py:115`, `parseo/eco_doppler.py:69` y
`extraccion/texto_pymupdf.py:57` son deliberados, para no acoplar `dominio/` a
`pipeline/` (`pipeline/etapas.py:1-16`).

#### Escenario: una etapa como string plano sigue siendo válida
- **Given** un `ErrorDocumento` construido con `etapa="parseo"` (string plano)
- **When** se valida el modelo
- **Then** la construcción MUST NOT fallar

## Requisito 3: test de deriva entre `_ETAPA` y el enum

El sistema **MUST** tener un test que recorra `src/` y falle si algún valor de un
`_ETAPA` declarado como constante de módulo no es miembro del enum unificado del
Requisito 1.

#### Escenario: agregar una etapa en un solo lado hace fallar el test
- **Given** un nuevo `_ETAPA = "clasificacion"` agregado a un parser, sin agregar
  `CLASIFICACION` al enum unificado
- **When** se corre el test de deriva
- **Then** el test falla, señalando el `_ETAPA` sin correspondencia

## Requisito 4: `ETAPAS_EMBUDO` derivado del enum con orden explícito

`web/embudo_corrida.py::ETAPAS_EMBUDO` **MUST** derivarse del enum unificado, no
declararse como lista de strings independiente. El orden de presentación **MUST**
decidirse explícitamente (constante de orden documentada), no heredarse por accidente
del orden de declaración del enum.

#### Escenario: agregar un miembro al enum no reordena el embudo sin decisión
- **Given** un nuevo miembro agregado al enum unificado en una posición arbitraria
- **When** se genera `ETAPAS_EMBUDO`
- **Then** el orden de presentación existente no cambia salvo que se edite también la
  constante de orden

#### Escenario: el vocabulario unificado no rompe la vista del embudo
- **Given** el enum unificado y `ETAPAS_EMBUDO` derivado de él
- **When** se calcula el embudo para un conjunto conocido de documentos (mismo fixture
  del Requisito 4 de `caracterizacion-comportamiento-actual`)
- **Then** el desglose por etapa coincide con el fijado en la Entrega 0
