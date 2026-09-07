# Propuesta: paralelismo de procesamiento

## Antes de leer: preguntá el denominador

**Los 100.000 documentos son proyección nuestra, no un dato del instituto.**

| Corpus real | Total secuencial | Con 8 procesos | ¿Vale este cambio? |
|---|---|---|---|
| 100.000 | ~13 h (10-16 h) | ~1,6-2,3 h | **Sí** |
| 10.000 | ~1,3 h (1,0-1,6 h) | ~10 min | **Marginal** — se corre de noche |

**Un email al instituto cuesta menos que cualquiera de estas optimizaciones y debe precederlas.**
Ese mismo email tiene que preguntar **dos** cosas, porque la segunda es igual de bloqueante:

1. ¿Cuántos documentos tiene el corpus?
2. **¿Los PDFs vienen en subcarpetas por paciente/episodio, o en una carpeta plana?**

Si el corpus es plano, la unidad de paralelización propuesta (`listar_grupos()` por
subdirectorio, `procesamiento-por-grupo/design.md:53-55`) devuelve **un solo grupo** y el
paralelismo rinde **cero**. Ver Dependencias.

## Intención

El objetivo del proyecto es llevar PDFs clínicos anonimizados a Postgres en AWS RDS
(`sa-east-1`). El presupuesto de tiempo trazado sobre el código
(`sdd/escritura-por-lotes/explore-presupuesto`) da **~13 h para 100k documentos: ~45% CPU local,
~55% espera de red contra la base**.

**La latencia de red se esconde con concurrencia; el trabajo de CPU no.** Por eso el paralelismo
captura **82-88% del total por ~245 líneas de `src/`**, mientras que la escritura por lotes que
se venía planificando captura **~5% por ~440 líneas**. Esta propuesta **reemplaza** a
`openspec/changes/escritura-por-lotes/`.

Hoy no hay nada de eso cableado:

| Afirmación | Realidad verificada con `rg` |
|---|---|
| "Un grupo es un paciente, un episodio" (`tareas.py:152-157`) | **Falso.** `procesar_carpeta.py:148` pasa **todas** las referencias de la carpeta a `procesar_grupo`. `listar_grupos()`/`GrupoArtefactos` sólo existen en `openspec/changes/*/design.md`, **no en `src/`**. |
| "Hay worker Celery" | **Falso.** `configurar_ejecutor` tiene **un llamador de producción**: `procesar_carpeta.py:112`. `procesar_grupo` se invoca sincrónica en `:148`. `trabajadores/app.py:29-67` configura una cola que nadie arranca. |
| "El pool de conexiones está configurado" | **Falso.** `procesar_carpeta.py:185` y `servir_panel.py:110` hacen `sa.create_engine(url)` pelado, sin `pool_pre_ping` ni `pool_recycle`. |

## Alcance

### Dentro

1. **`listar_grupos() -> Iterator[GrupoArtefactos]`** en el `Protocol` `FuenteDeArtefactos` y en
   `FuenteLocal` (`ingesta/fuente.py:47,117`), un grupo por subdirectorio inmediato.
   `LanzadorCorrida.lanzar()` (`lanzador_corrida.py:127-131`) pasa a devolver grupos, no una
   tupla plana. **Es el prerrequisito estructural**: sin partición por paciente no hay unidad
   que paralelizar.
2. **Despachador multiproceso** (`concurrent.futures.ProcessPoolExecutor`) que invoca
   `procesar_grupo` por grupo, con `scripts/procesar_carpeta.py` como llamador real.
3. **`pool_pre_ping` + `pool_recycle` + `pool_size`** en `procesar_carpeta.py:185` y
   `servir_panel.py:110`. Es **corrección, no velocidad**: contra RDS, una conexión muerta por
   idle timeout manda un documento a cuarentena por un problema de infraestructura.
4. **`IntegrityError` en `registrar_vinculo` (`postgres.py:67-83`) y `escribir_episodio`
   (`postgres.py:107-110`)**. Ambos hacen `get` + `add` sin capturar la carrera, a diferencia de
   `escribir_registro` (`postgres.py:150-155`), que ya la trata bien y es el patrón a copiar.
   Con N procesos, dos que resuelvan el mismo paciente a la vez chocan → reintento agotado →
   cuarentena falsa.

### Fuera, con motivo

| Excluido | Motivo |
|---|---|
| **Eliminar las pasadas redundantes del NER** (7-11% del total, ~60 líneas) | **Es independiente del paralelismo y merece su propio cambio.** Toca `bitacora_segura.py:76`, que es **defensa en profundidad deliberada** (`bitacora_segura.py:21-22`). Quitar una capa de seguridad requiere argumentar que la whitelist de `resumen_trazable()` (`pipeline/resultado.py:45-50`: hashes HMAC y enums) alcanza — ese argumento necesita su propio spec y su propia revisión. Mezclarlo con un cambio de concurrencia hace que **ninguno de los dos se revise bien**. Rinde igual antes o después. |
| **Worker Celery + Redis** | Ver Enfoque. Se descarta la infraestructura, **no se borra el código**: `trabajadores/app.py` y `tareas.py` quedan intactos. |
| **Escritura por lotes / sesión compartida por grupo** (`escritura-por-lotes` PR 2) | ~5% del total por ~440 líneas, y su premisa de "grupo de 3" no existía en producción. |
| **`SELECT ... IN` de idempotencia por grupo** (~8% del total, ~40 líneas) | Requiere cambiar el `Protocol` de `DestinoEscritura`. Se difiere hasta que exista agrupamiento real; después es barato. |
| **Modelo PII más chico** | Degrada el recall. Un falso negativo es PII sin anonimizar en el dataset. **Rechazado por seguridad.** |
| **GPU** | Cambia la topología de despliegue (estación Windows aislada). |

## Enfoque

### Decisión 1: `ProcessPoolExecutor`, no Celery + Redis

| Criterio | `ProcessPoolExecutor` | Celery + Redis |
|---|---|---|
| **Quién lo opera** | Nadie. Es una bandera del script (`--procesos N`). | Alguien instala, asegura, monitorea y respalda Redis. **Ese alguien es un médico o el tesista**, no un equipo de plataforma. |
| **Superficie de PII** | Las referencias `{id_documento, uri, sha256}` nunca salen del proceso padre. | La `uri` es una ruta de archivo, y **el nombre de carpeta puede ser PII** — el propio `procesamiento-por-grupo/design.md:61` lo reconoce al hashear la ruta para el `id_grupo`. Con Redis, esas rutas viajan y **quedan en reposo** en un servicio fuera del límite del proceso. **Argumento decisivo.** |
| **Pepper HMAC** | Los hijos heredan `os.environ` (fork en Linux; en Windows `spawn` copia el entorno del padre). `obtener_pepper()` (`almacen_pepper.py:56-74`) corre igual en cada hijo: **nunca en disco, nunca por el broker**. | También funciona vía el entorno del worker, pero el worker es un demonio de larga vida cuyo entorno gestiona systemd/shell: **un lugar más donde vive el secreto**. |
| **Reanudación de una corrida** | La base sigue siendo la única autoridad: estados de `corrida`/`documento` + idempotencia por `clave_documento` (`postgres.py:147`). Se vuelve a correr el script y lo ya escrito se saltea. | Agrega una **segunda fuente de verdad en conflicto**: mensajes sin ACK en Redis. `acks_late=True` + `reject_on_worker_lost=True` reencolan trabajo que la base ya considera hecho. |
| **Panel web** | Sin cambios: lee de la base. | Sin cambios: lee de la base. |
| **Costo** | ~70 líneas, cero infraestructura. | ~60 líneas de entrypoint **más** instalar y operar Redis. |

**Elección: `ProcessPoolExecutor`.** Captura el mismo 85% sin agregar un servicio que alguien
tiene que operar ni una superficie de PII en reposo. `procesar_grupo` sigue siendo la misma tarea
Celery, invocada en directo — exactamente como hoy hace `procesar_carpeta.py:148`. **Si mañana
aparece un equipo de plataforma, migrar el despachador a `.delay()` es una línea.**

### Decisión 2: grado de concurrencia — razonamiento, no número mágico

Con la mezcla ~45% CPU / ~55% red, el speedup con N procesos y C núcleos físicos es
aproximadamente `1 / (0,45/min(N,C) + 0,55/N)`:

| N | C=8 | Lectura |
|---|---|---|
| 4 | 4,0× | Ambos términos escalan. |
| 8 | 8,0× | **Punto natural: N = C.** |
| 16 | ~11,1× | El término de CPU **deja de mejorar**; sólo se recorta la espera de red. |
| 32 | ~13,3× | Rendimientos claramente decrecientes. |

Pasado `N = C`, cada proceso extra **sólo** compra latencia de red, y cuesta caro: una copia de
`es_core_news_lg` en RAM por proceso (**cientos de MB cada una**) más un pool de conexiones
contra RDS. **Riesgo que la exploración no cubrió: la memoria de los modelos, no el CPU, puede
ser el techo real.**

**Default `N = núcleos físicos`, configurable, tope duro en `2 × núcleos`.** Se mide antes de
subirlo.

### Decisión 3: la partición tiene que respetar al paciente

`ejecutor.py:87` fija `_GRUPO_ES_UNIDAD_COMPLETA = True`, y `_coordinar_resueltos`
(`ejecutor.py:459-480`) manda a cuarentena como `EPISODIO_INCOMPLETO` a todo documento cuyo
compañero de episodio falte en el lote. **Si el LAB y el ECG del mismo paciente caen en
particiones distintas, los dos van a cuarentena.** Por eso `listar_grupos()` no es opcional ni
diferible: es el cambio que hace correcta la partición.

Corolario: **la partición debe ser disjunta**. La deduplicación por contenido es global a la
enumeración (`procesamiento-por-grupo/design.md:72-74`), así que un PDF idéntico en dos carpetas
se descarta en la segunda — el grupo queda incompleto y va a cuarentena. Es la verdad, no un bug.

### Efecto lateral positivo sobre la RAM

`procesar_lote` (`ejecutor.py:324-351`) acumula **todos** los `resueltos` en memoria. Con la
carpeta entera como lote, eso es 100k documentos (320 MB medidos @10k; @100k sin medir).
**El agrupamiento lo alivia, no lo agrava**: cada proceso retiene sólo los resueltos de su grupo.
El paralelismo multiplica ese pico por N, pero N × (un grupo) es órdenes de magnitud menor que
un lote de 100k.

## Capacidades

### Nuevas
- `despacho-paralelo`: enumeración de grupos, despacho multiproceso, grado de concurrencia,
  configuración de pool contra RDS.

### Modificadas
- `procesamiento-por-grupo`: `listar_grupos()` pasa de diseñado a implementado; el grupo deja de
  ser la carpeta entera y pasa a ser el subdirectorio.
- `escritura-idempotente`: `registrar_vinculo` y `escribir_episodio` ganan la misma tolerancia a
  carrera que ya tiene `escribir_registro`.

## Áreas afectadas

| Área | Impacto | Qué cambia |
|---|---|---|
| `src/anonimizacion/ingesta/fuente.py` | Modificar | `GrupoArtefactos`; `listar_grupos()` en `Protocol` y `FuenteLocal` |
| `src/anonimizacion/ingesta/lanzador_corrida.py` | Modificar | `lanzar()` devuelve grupos |
| `src/anonimizacion/salida/destinos/postgres.py` | Modificar | `IntegrityError` en `registrar_vinculo` y `escribir_episodio` |
| `scripts/procesar_carpeta.py` | Modificar | Despachador multiproceso, `--procesos`, config de pool |
| `scripts/servir_panel.py` | Modificar | Config de pool |
| `src/anonimizacion/trabajadores/app.py`, `tareas.py` | **Sin cambios** | Se conservan para una migración futura a Celery |

## Riesgos

| Riesgo | Prob. | Mitigación / red de seguridad |
|---|---|---|
| **El corpus real es una carpeta plana** → `listar_grupos()` devuelve 1 grupo y el paralelismo rinde cero | **Media** | **Bloqueante. Se pregunta al instituto ANTES de implementar.** Ver Dependencias. |
| Se degrada el aislamiento de fallo por documento | Baja | `try/except` por ítem (`ejecutor.py:328,357`) y `_ejecutar_con_reintentos` (`ejecutor.py:187-189`) quedan intactos — el paralelismo opera **por encima** de `procesar_lote`, no dentro. Red: `tests/pipeline/test_ejecutor.py:309,445,486` y `tests/integracion/test_lote_aislamiento.py`. |
| Se rompe la idempotencia | Baja | La autoridad es la restricción única de `estudio`, no el `SELECT` (`postgres.py:122-128`). Red: `tests/integracion/test_reprocesar_no_duplica.py`. |
| **Se rompe la invariante del embudo** | Baja | `calcular_embudo` (`embudo_corrida.py:196-197`) hace `residuo = entraron - (publicados + apartados)`, `cierra = residuo >= 0`. `entraron` se fija en el inventario, en **un solo** proceso. N procesos sólo achican el residuo. `residuo < 0` requeriría doble contabilización, que sólo ocurre si la partición **no es disjunta**. Red: `tests/web/test_embudo_corrida.py:342`, `tests/integracion/test_embudo_corrida_integracion.py`. |
| Cuarentena falsa por carrera en el puente de paciente | **Alta sin el punto 4** | Por eso el `IntegrityError` va en el **PR 1**, antes de que exista el segundo proceso. |
| RAM: N copias de `es_core_news_lg` | Media | Tope duro `2 × núcleos`; se mide el pico antes de subir el default. |
| RDS agota `max_connections` | Baja | `pool_size` explícito; presupuesto = N × `pool_size` + el panel. |

## Plan de reversión

Cada rebanada revierte sola con `git revert` de su merge commit.

- **PR 3 (paralelismo)**: revertir deja el despachador secuencial por grupo. Sin cambio de
  esquema, sin migración, sin dato escrito distinto.
- **PR 2 (grupos)**: revertir vuelve a la carpeta entera como lote. Es el comportamiento de hoy.
- **PR 1 (correcciones)**: no debería revertirse — corrige fallos reales. Si hiciera falta,
  vuelve al `create_engine` pelado y al `get`+`add` sin captura.

**Ninguna rebanada toca el esquema de la base.** No hay migración que deshacer, y una corrida
interrumpida se reanuda por idempotencia (`clave_documento`) sin importar en qué rebanada esté
el código.

## Dependencias

1. **BLOQUEANTE — respuesta del instituto**, en un solo email: (a) tamaño real del corpus,
   (b) si los PDFs vienen agrupados en subcarpetas por paciente/episodio. Sin (b), la unidad de
   paralelización no existe y hay que rediseñar el agrupamiento sobre otra señal.
2. **Docker no está disponible en esta máquina** → no hay Postgres real. **La mitad de red del
   presupuesto no se puede medir acá.** Ver Criterio de éxito.
3. El PR 2 depende del PR 1; el PR 3 depende del PR 2.

## Criterio de éxito — y qué se puede medir hoy, honestamente

### Se puede verificar hoy (SQLite + banco offline)

- [ ] `listar_grupos()` devuelve un grupo por subdirectorio, con dedup y tope de tamaño heredados.
- [ ] La partición es **disjunta**: ningún `id_documento` aparece en dos grupos.
- [ ] Con N procesos, el embudo **cierra** (`residuo >= 0`) y `publicados + apartados == entraron`.
- [ ] Ningún documento se duplica en `estudio` con N procesos concurrentes.
- [ ] Dos procesos que registran el mismo `id_alt_paciente` a la vez → ninguno va a cuarentena.
- [ ] El aislamiento de fallo por documento sigue verde: un documento roto no arrastra a su grupo.
- [ ] **Escalado de CPU**: tiempo de reloj del pipeline con N=1,2,4,8, midiendo **sólo** el
      pipeline. El reloj del banco (`ejecutar_corpus.py:206-210`) incluye la generación de 1005
      PDFs y un verificador cuadrático (`corpus_piloto.py:132-134`); hay que instrumentar por
      fuera de esos dos o el número no significa nada.

### NO se puede verificar hoy — y no se va a maquillar

- **La mitad de red (~55% del presupuesto) no es medible sin RDS real.** El banco usa dobles
  (`_MotorPiiOffline`, `_DestinoMemoria` en `tests/fixtures/corpus_piloto.py:38,176`): **no
  ejerce ni una sola conexión de red**, así que **no sirve como evidencia de rendimiento real**.
- **El 82-88% de reducción es una ESTIMACIÓN con rango**, derivada de un RTT Buenos
  Aires–São Paulo de 30-50 ms razonado por distancia de fibra, **no medido**. El total baja de
  ~13 h a **~1,6-2,3 h estimadas**.
- **Ningún número de latencia de esta propuesta se midió.** Cuando haya RDS o Docker, se mide y
  se corrige.

### Cómo evitamos "algo verde que valida un cableado que producción no usa"

Este patrón apareció **cinco veces** en este repositorio, `listar_grupos()` incluido. Regla dura
para este cambio:

> **Ninguna función nueva se mergea sin un llamador de producción en `scripts/` dentro del mismo
> PR.** Cada rebanada agrega un test centinela — al estilo de
> `tests/integracion/test_wiring_produccion.py` — que afirma que
> `scripts/procesar_carpeta.py` **pasa realmente por el código nuevo**, no que el código nuevo
> funcione en aislamiento.

`configurar_extractor` (`tareas.py`, sin llamador de producción, sólo tests) es el
contraejemplo vivo que no queremos repetir.

## Entrega — `auto-chain` + `stacked-to-main`

**Estimación: ~250 líneas de `src/` + ~300 de tests ≈ 550 líneas cambiadas.** Supera el
presupuesto de 400. Se corta en tres rebanadas apiladas contra `main`:

```
main
 └─ PR 1  correcciones de robustez         📍 arranca acá
     └─ PR 2  agrupamiento real
         └─ PR 3  despacho paralelo
```

| PR | Contenido | Líneas est. | Verificación | Reversión |
|---|---|---|---|---|
| **1** | `pool_pre_ping`/`recycle`/`size` en ambos scripts + `IntegrityError` en `registrar_vinculo` y `escribir_episodio` | ~120 | Test de carrera con dos sesiones concurrentes sobre SQLite; centinela de que ambos scripts construyen el engine con la config | Autónomo. Corrige fallos reales; vale aunque no siga nada más. |
| **2** | `GrupoArtefactos` + `listar_grupos()` + `LanzadorCorrida` devolviendo grupos + `procesar_carpeta.py` iterando grupos **secuencialmente** | ~290 | Embudo cierra; partición disjunta; RAM pico baja vs. hoy; centinela de wiring | Vuelve a la carpeta entera como lote = comportamiento actual. |
| **3** | `ProcessPoolExecutor` + `--procesos` + tope de concurrencia | ~200 | Escalado de CPU N=1,2,4,8; no-duplicación con N procesos; aislamiento de fallo intacto | Deja el despacho secuencial por grupo del PR 2. |

**El PR 2 entrega valor solo** aunque el PR 3 nunca se mergee: arregla la acumulación en RAM y
convierte la transacción implícita de 100k documentos en unidades del tamaño de un paciente.
