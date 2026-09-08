# Propuesta: escritura por lotes contra Postgres

## Conclusión de archivo (2026-09-08) — DESCARTADA, no implementada

**Esta propuesta no se implementó. Se archiva como investigación cerrada, no como trabajo
pendiente.**

Motivo: la propia propuesta (ver "Preguntas abiertas" #1 más abajo) dejaba el criterio de éxito
de latencia bloqueado por falta de un Postgres real contra el cual medir. Ese bloqueo se resolvió
después, durante la implementación de `openspec/changes/archive/paralelismo-de-procesamiento/`
(ver su `proposal.md`, sección "Datos medidos durante el PR 1"): con Docker disponible se midió
contra Postgres 16 real (no SQLite) que un documento publicado paga **6,67 round trips SQL**, no
los ~22 que sugería una medición previa contra SQLite — ese 22 era un artefacto del driver
(`pysqlite` emite un `INSERT` por fila; `psycopg` agrupa con `insertmanyvalues`), no una
propiedad del pipeline.

Con el número real medido, la propia estimación de esta propuesta ("20-30% menos viajes por
grupo, no un orden de magnitud", más arriba) deja de justificar el riesgo que ella misma señala
como "Alta probabilidad" en su tabla de riesgos: sesión compartida por grupo + `SAVEPOINT` +
cambio de `Protocol` de `DestinoEscritura`, con la asimetría SQLite/Postgres explícitamente no
verificable en CI. `paralelismo-de-procesamiento` captura 82-88% del tiempo total por un cambio
más chico y sin ese riesgo — ver su proposal.md, sección "Intención": *"La latencia de red se
esconde con concurrencia; el trabajo de CPU no. [...] el paralelismo captura 82-88% del total
por ~245 líneas de `src/`, mientras que la escritura por lotes [...] captura ~5% por ~440
líneas. Esta propuesta reemplaza a `openspec/changes/escritura-por-lotes/`."*

**No se archiva por abandono ni por falta de tiempo: se archiva porque el dato que la habría
justificado, una vez medido, no la justifica.** El directorio nunca llegó a versionarse en git
(quedó como cambio sin seguimiento) porque el trabajo de diseño se interrumpió al surgir la
medición real; se agrega a control de versiones recién en este archivado, para que la
investigación y su conclusión queden trazables en vez de perderse.


Bajar los viajes a base por grupo sin perder el aislamiento de fallo por documento, que hoy es la única razón por la que un ECG corrupto no se lleva puestos el laboratorio y el ecocardiograma del mismo paciente.

## Intención

| Pregunta | Respuesta |
|---|---|
| Problema | Cada documento paga 2-3 viajes a base (verificado en `postgres.py:67,99,114` y `resolutor_claves.py:186`). Un grupo típico de 3 estudios paga 6-9. Contra RDS `sa-east-1` esa latencia todavía no está medida y no está en las 7,4 h proyectadas. |
| Por qué ahora | Los 266,8 ms/pdf medidos salen de un banco con dobles (`tests/fixtures/corpus_piloto.py:38,46` — `_MotorPiiOffline`, `_DestinoMemoria`). Ningún número histórico incluye E/S a base. La proyección a 100k documentos está incompleta por diseño. |
| Éxito | Menos `COMMIT` por grupo, con el aislamiento por documento intacto y verificable. |

## Decisión central: aislamiento por documento, sostenido con `SAVEPOINT`

**Decisión: alternativa (a) — sesión compartida por grupo con `begin_nested()` por documento. NO se degrada el aislamiento a nivel de grupo.**

No es una preferencia estética. Un grupo son tres estudios del mismo paciente; degradar el aislamiento significa que un ECG con un parseo raro borra dos documentos clínicos buenos. En un corpus médico eso no es una pérdida de rendimiento, es pérdida de datos del paciente.

Rechazos, con motivo:

| Alternativa | Rechazo |
|---|---|
| (b) `executemany` + `ON CONFLICT DO NOTHING` | Reabre la Decisión 3 de `escritura-idempotente/design.md`, tomada tras un bug real en `vinculo_paciente`. Para `estudio` sería defendible; para el resto no. Reestructura `_emitir`. No paga el riesgo. |
| (c) Acumulador con volcado configurable | Es (a) con una perilla de más y contabilidad propia. La perilla sin la contabilidad detrás ya está rechazada en este repo (`ejecutor.py:85-87`). |
| (d) `COPY` + tabla temporal | Rompe la portabilidad SQLite/Postgres. Obligaría a dos implementaciones de escritura, o a que los tests dejen de tocar el camino real. Es exactamente el patrón que este repo combate. |

### Corrección al alcance de la sesión compartida

La sesión compartida cubre **solo `_emitir`** (`ejecutor.py:519`): `escribir_episodio` + `escribir_registro`. **NO** cubre `resolver_claves`.

Motivo de corrección, no de rendimiento: `registrar_vinculo` (`postgres.py:67`) persiste el hecho "este `id_alt_paciente` es ambiguo", y ese hecho debe sobrevivir aunque el documento después falle. Meterlo en la transacción del grupo significa que un `ROLLBACK` borra una ambigüedad legítimamente detectada. Eso viola "una vez ambiguo, siempre ambiguo" (`postgres.py:75-76`).

Consecuencia honesta: la ganancia es acotada. Se eliminan ~2 de 6-9 viajes por grupo (los `COMMIT` de `escribir_registro` de los documentos 2 y 3). Los `SELECT` de idempotencia y los 1-2 viajes de resolución de claves siguen ahí. **Estimación: 20-30% menos viajes por grupo, no un orden de magnitud.**

## Alcance

### Entra

- Sesión compartida por grupo en `_emitir`, con `begin_nested()` por documento en `EscritorPostgres`.
- Método explícito de apertura/cierre de lote en `DestinoEscritura` (`ejecutor.py:94`). El Protocol cambia; los dobles de test también.
- **`escribir_episodio` gana captura de `IntegrityError` ante carrera** (`postgres.py:99`, hoy no la tiene). Entra porque este cambio lo mueve adentro de una transacción compartida: hoy una carrera envenena una sesión descartable; dentro de la transacción del grupo envenenaría el grupo entero. El hueco preexistente se vuelve un defecto activo.
- Configuración explícita del pool: `pool_pre_ping`, `pool_size`, `pool_recycle` en `scripts/procesar_carpeta.py:185` y `scripts/servir_panel.py:110`, hoy `sa.create_engine(url)` a secas. Con RDS y workers de larga vida, sin `pre_ping` una conexión muerta cuesta un reconecte TCP+TLS completo — es la latencia más cara y la más barata de arreglar.

### No entra, y por qué

| Excluido | Motivo |
|---|---|
| `ON CONFLICT` en cualquier tabla | Decisión 3 de `escritura-idempotente/design.md` sigue en pie. Nada nuevo la contradice. |
| Agrupar `resolver_claves` | Rompe la persistencia de la ambigüedad (arriba). |
| `PublicadorBundles`, `EscritorParquet` | Huérfanos de producción. Ruido. |
| Medición de latencia contra Postgres real | No hay Docker en esta máquina. Sin instancia RDS de prueba no hay número. No se maquilla. |
| Cambiar el tamaño de grupo | El grupo ya es la unidad de coordinación de episodios. |

## Criterio de éxito

| Criterio | Verificable hoy |
|---|---|
| Un fallo de escritura de un documento no impide la escritura de los otros del mismo grupo | **Sí** — `tests/pipeline/test_ejecutor.py:445` debe seguir verde sin modificarse |
| `COMMIT` por grupo pasa de N a 1 en `_emitir` | **Sí** — contando eventos de commit sobre el `Engine` de SQLite |
| Reprocesar un grupo no duplica filas | **Sí** — `tests/salida/destinos/test_postgres.py` contra SQLite |
| Camino real end-to-end sigue escribiendo 3 filas | **Sí** — `tests/scripts/test_procesar_carpeta.py:108-131`, que usa `EscritorPostgres` real |
| Latencia por grupo contra RDS baja X% | **NO. Bloqueado.** Sin Postgres con latencia de red real cualquier número es estimación. Se declara pendiente, no se inventa. |

## Compatibilidad SQLite / Postgres — y el riesgo de test fantasma

`SAVEPOINT` existe en ambos vía `session.begin_nested()`. Pero hay una asimetría que **no se puede verificar en CI hoy**:

En Postgres, una excepción dentro de una transacción deja la transacción en estado abortado; todo comando posterior falla hasta el `ROLLBACK`. SQLite es más permisivo. Si el `except IntegrityError: pass` de `escribir_registro` (`postgres.py:150`) queda fuera del `begin_nested()`, **el test pasa en SQLite y producción se rompe en Postgres.** Ese es literalmente el patrón que este repo ya encontró cinco veces.

Cómo se evita, sin fingir cobertura:
1. El `except IntegrityError` DEBE quedar dentro del `begin_nested()`, para que el rollback sea al `SAVEPOINT` y la sesión siga usable.
2. Se declara explícitamente en el spec y en el código que este comportamiento **NO está verificado contra Postgres real**, con el test que faltaría nombrado. Un hueco declarado es honesto; un test verde en SQLite presentado como cobertura de Postgres es mentira.
3. `_ejecutar_con_reintentos` (`ejecutor.py:159`) reintenta la llamada completa. Con sesión compartida, cada reintento debe partir de un `SAVEPOINT` limpio — de lo contrario el segundo intento corre sobre una sesión ya rota. Necesita test dedicado.

## Riesgo de regresión

| Riesgo | Probabilidad | Red de seguridad |
|---|---|---|
| Se degrada el aislamiento sin darnos cuenta | Media | `test_ejecutor.py:309,445,486` y `tests/pipeline/test_particion_total_del_lote.py`. **Ninguno se modifica.** Si hay que tocarlos para que pasen, la propuesta falló. |
| Sesión envenenada en Postgres, verde en SQLite | **Alta** | Punto 1 de arriba + hueco declarado |
| Idempotencia rota al mover el `SELECT` a sesión compartida | Baja | `tests/salida/destinos/test_postgres.py` |
| Reintento sobre sesión rota | Media | Test nuevo dedicado (hoy no existe) |
| Cambio del Protocol rompe dobles de test | Alta pero visible | Falla al importar; `_EscritorFake`, `_DestinoMemoria` |

## Tamaño y entrega

Estimado ~440 líneas cambiadas sobre 6-8 archivos. **Supera el presupuesto de 400 líneas de revisión.** Con `auto-chain` + `stacked-to-main`, dos rebanadas:

| PR | Contenido | Líneas |
|---|---|---|
| 1 | `IntegrityError` en `escribir_episodio` + configuración de pool | ~120 |
| 2 | Sesión compartida + `SAVEPOINT` + cambio de Protocol + tests | ~320 |

PR 1 es autónomo, no cambia contratos y entrega valor solo. PR 2 depende de él.

## Capacidades

### Nuevas
Ninguna.

### Modificadas
- `escritura-idempotente`: la idempotencia pasa a ejercerse dentro de una transacción compartida por grupo; el `SAVEPOINT` es el nuevo límite de reversión.
- `batch-processing`: el aislamiento de fallo por documento se mantiene, pero ahora se sostiene por `SAVEPOINT` y no por transacción independiente. El requisito no cambia; el mecanismo sí, y debe quedar escrito.

## Plan de reversión

`git revert` de cada PR por separado. No hay migración de esquema, no hay cambio de datos, no hay estado persistido nuevo. PR 2 revierte solo; PR 1 revierte solo. El único acoplamiento es el Protocol, que vive entero en PR 2.

## Preguntas abiertas

1. ¿Hay presupuesto para una instancia RDS de prueba? Sin eso, el criterio de latencia queda declarado y sin cerrar indefinidamente.
2. ¿La carrera en `escribir_episodio` ya se manifestó en producción, o es teórica? No cambia la decisión, cambia la prioridad de PR 1.
