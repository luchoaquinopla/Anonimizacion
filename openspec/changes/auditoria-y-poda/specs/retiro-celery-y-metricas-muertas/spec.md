# Especificación: retiro de capacidad no operada

Capacidad nueva (Entrega 5). Retira Celery/Redis (cáscara decorativa, sin llamador de
producción real) y `observabilidad/metricas.py` (métricas de sólo escritura), sin tocar
`despacho_paralelo.py::MetricasDespacho`, que sí se lee. Evidencia:
`trabajadores/app.py:23`, `tareas.py:150`, `deploy/operacion-institucional.md:48-51`,
`observabilidad/metricas.py:41-103`, `despacho_paralelo.py:330`
(auditoria/consolidado-2026-09, obs #1338).

## Requisito 1: sin importaciones de Celery en `src/`

Ningún módulo bajo `src/anonimizacion/` **MUST** importar `celery`. `procesar_grupo`
**MUST** invocarse en directo, como ya hace todo llamador de producción
(`scripts/procesar_carpeta.py:171`).

#### Escenario: `src/` queda libre de Celery
- **Given** el árbol `src/anonimizacion/` después de la Entrega 5
- **When** se busca la cadena `import celery` (o `from celery`)
- **Then** no hay coincidencias

#### Escenario: `procesar_grupo` sigue funcionando invocado en directo
- **Given** un grupo de documentos a procesar
- **When** se invoca `procesar_grupo` directamente (sin `.delay()`)
- **Then** el grupo se procesa igual que antes de la Entrega 5

## Requisito 2: la documentación de despliegue no promete Celery

`deploy/operacion-institucional.md` **MUST NOT** mencionar ninguna variable `CELERY_*`
ni instruir a IT del instituto a configurarlas.

#### Escenario: documento sin variables Celery
- **Given** `deploy/operacion-institucional.md` después de la Entrega 5
- **When** se busca la cadena `CELERY_`
- **Then** no hay coincidencias

## Requisito 3: métricas de sólo escritura retiradas

`observabilidad/metricas.py` y `observabilidad/bitacora_segura.py:56 CODIGOS_SEGUROS`
**MUST** eliminarse del árbol de código.

#### Escenario: módulo de métricas muertas ausente
- **Given** el árbol `src/anonimizacion/observabilidad/` después de la Entrega 5
- **When** se lista su contenido
- **Then** no existe `metricas.py`
- **And** `bitacora_segura.py` no declara `CODIGOS_SEGUROS`

## Requisito 4: `MetricasDespacho` permanece intacta y legible

`despacho_paralelo.py::MetricasDespacho` **MUST NOT** modificarse por esta entrega, y el
reporte de corrida que la lee (`scripts/procesar_carpeta.py:219-223` o su equivalente
tras la Entrega 4) **MUST** seguir funcionando exactamente igual que antes.

#### Escenario: el reporte de corrida sigue leyendo `MetricasDespacho`
- **Given** el mismo fixture del Requisito 5 de `caracterizacion-comportamiento-actual`
- **When** se genera el reporte de corrida después de la Entrega 5
- **Then** el contenido coincide con el fijado en la Entrega 0
