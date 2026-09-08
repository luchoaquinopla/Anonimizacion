# Propuesta: panel de operación

## Intención

El codirector médico va a conectar el pipeline a la base del Instituto de Cardiología y va a mirar
corridas de 1.000 a 100.000 PDFs que duran ocho a diez horas. Hoy no puede mirar nada: el camino de
producción no emite una sola señal sobre su propio avance. Una corrida es una caja negra que
termina o no termina.

## El problema

Tres hechos verificados en el código:

1. `procesar_grupo` → `EjecutorPipeline.procesar_lote` **no conoce `corrida_id`**. El mensaje de
   cola es exactamente `{id_documento, uri, sha256}` (`pipeline/ejecutor.py:107-116`).
2. Ninguna tabla de salida ni `cuarentena` tiene `corrida_id` (`salida/modelos_orm.py:83-241`). No
   existe forma de preguntar "qué produjo esta corrida".
3. `ServicioCorridas` (`web/rutas_corridas.py:22`) es un `Protocol` sin implementación, y **ningún
   proceso sirve la app WSGI**. El único doble que existe es `_ServicioFake` en tests.

Y el patrón de fondo, que es el riesgo mayor de este cambio: **van tres subsistemas construidos,
verdes y desconectados** — la máquina de estados de corrida con `RepositorioCorridas`; las tareas
`procesar_extraccion_minima`/`_completa`, que sólo invoca `tests/trabajadores/test_tareas.py`; y
`observabilidad/metricas.py` + `observabilidad/bitacora_segura.py`, con cero imports en producción
(el comentario de `pipeline/resultado.py:10` dice "todavía no construida" sobre un módulo que sí
está construido). Este cambio **no puede agregar la cuarta**.

## Qué muestra el panel, y qué no

Un embudo por **etapa real** del pipeline (`pipeline/etapas.py`): cuántos documentos pasaron cada
etapa, dónde se cayeron y con qué código, throughput y un **rango** de tiempo restante.

No se usa el vocabulario de `EstadoDocumentoCorrida` (`inventariado`, `clasificado`,
`extraido_minimo`, `asociado`…). Describe un flujo de extracción por etapas que el camino real **no
ejecuta**: mostrarlo produciría avance falso, con documentos saltando de `inventariado` a
`aprobado`. A 100.000 documentos, "este documento está en parseo" dura milisegundos y no informa;
lo que informa es el agregado.

## De dónde salen los conteos

Se evaluaron tres vías. **Gana derivar el embudo de lo que ya se persiste**: cero escrituras nuevas
en el camino caliente, `corrida_id` es una columna más en filas que igual se escriben.

| Vía | Costo en una corrida de 100k | Veredicto |
|---|---|---|
| Derivar de lo persistido | 0 escrituras nuevas; una consulta agregada por refresco | **Elegida** |
| Tabla de contadores agregados | ~700.000 incrementos con contención sobre la fila `(corrida, etapa)`; consistencia transaccional con la escritura de salida | Rechazada: resuelve una carga que no existe (1-5 espectadores) y compra un cuello de botella |
| Avance por documento en `documento_corrida` | ~900.000 `UPDATE` con bloqueo optimista y sus reintentos | Rechazada: además implementa a medias lo que D3 declara fuera de alcance |

### La hipótesis se sostiene, con tres agujeros que hay que tapar

Verificado contra `procesar_lote`: cada `ItemLote` sale hoy por una de dos puertas —
`_resolver_documento` exitoso, o `ErrorParseo` → `_a_fallo` → cuarentena— y `_coordinar_resueltos`
reparte los resueltos entre aprobados y cuarentena. La partición es real. Pero:

1. **`episodios_pendientes` está vacío sólo por accidente afortunado.** `ejecutor.py:366` pasa
   `corrida_cerrada=True` fijo. Con `False`, los documentos pendientes no entran ni en
   `resueltos_aprobados` ni en `fallos`: el embudo los contaría en vuelo para siempre. Es una
   invariante a fijar con centinela, no una propiedad del diseño.
2. **`_a_fallo` traga el fallo de escritura de cuarentena** (`ejecutor.py:468-475`). Documento
   caído + cuarentena caída = ninguna fila en ningún lado. La resta `entraron − salida − cuarentena`
   NO es "en vuelo": es "en vuelo más perdidos". El panel **MUST** mostrar ese residuo como columna
   propia —"sin desenlace registrado"— en vez de disfrazarlo de trabajo en curso. Hace visible una
   falla de infraestructura que hoy es invisible.
3. **`cuarentena` no tiene restricción única** (`modelos_orm.py:229-241`: `id` autoincremental,
   `id_documento` indexado pero no único), mientras el lado de salida sí es idempotente
   (`uq_estudio_clave_documento`, línea 114). Reprocesar una corrida no duplica `estudio` pero sí
   duplica `cuarentena`: contar filas sobrecuenta caídos. Se cuenta por documento distinto y se
   agrega la unicidad.

### Dos hallazgos que corrigen el alcance previsto

- **`estudio` es el contador correcto de "llegó a salida"**: una fila por documento publicado, con
  `clave_documento` único. No `episodio` (una por grupo) ni las de medición (N por documento). Pero
  **`estudio` no tiene columna de fecha**: sin `creado_en` no hay tasa ni tiempo estimado. Hay que
  agregarle `corrida_id` **y** `creado_en`.
- **`deteccion` y `deteccion_pii` nunca producen cuarentena.** El detector es puro y no lanza
  (`ejecutor.py:295`); el fallo de tipo desconocido se registra como `parseo`
  (`parseo/registro.py:36`); la clasificación de PII no lanza. Las etapas que sí aparecen en
  `cuarentena.etapa` son `ingesta`, `extraccion`, `parseo`, `reconciliacion`, `coordinacion`,
  `pseudonimizacion` y `salida`. El panel las declara de paso en vez de dibujar barras vacías que
  parecen pérdida cero medida.

## El stack, y el disparador para cambiarlo

Se sigue con WSGI crudo, HTML servido y polling con JavaScript en línea (`fetch` + `setInterval`
cada uno o dos segundos). Con 1-5 espectadores son 2,5-5 solicitudes por segundo sobre un índice:
carga irrelevante. SSE sobre WSGI síncrono clava un worker por conexión durante horas. FastAPI
obligaría a rutas `def` síncronas igual —SQLAlchemy síncrono bloquea el event loop entero— y queda
como Flask con pasos de más. Un SPA exige Node, que no existe en la máquina del instituto, y duplica
el stack de pruebas.

**Disparador explícito**: cuando el panel pase de unas seis rutas o aparezcan formularios reales,
Flask síncrono pasa a ser la elección correcta y esta decisión se revisa.

## Alcance

### Dentro

- `corrida_id` viajando por el camino de producción hasta `estudio`, `episodio`, las tablas de
  medición y `cuarentena`; más `creado_en` en `estudio`.
- Inventario de la corrida al arranque: `documento_corrida` como denominador ("entraron"), usando
  el `RepositorioCorridas` que ya existe. Una escritura por documento, una sola vez, fuera del
  camino caliente.
- Unicidad de cuarentena por documento dentro de la corrida.
- Índice compuesto `(corrida_id, estado)` en `documento_corrida`; hoy son dos índices de una
  columna (`migrations/versions/0002_corridas_durables.py:43-44`).
- Cableado de `ColectorMetricas` y `BitacoraSegura` al `EjecutorPipeline` por inyección opcional,
  con el mismo patrón de dependencias del `__init__` (`ejecutor.py:188-219`), sin romper el
  aislamiento de fallo por documento ni la disciplina de "sin PII en cola, logs ni DLQ".
- Implementación real de `ServicioCorridas` y punto de entrada que sirva la app WSGI.
- Modelo de lectura del embudo + endpoint JSON + pantalla, siguiendo el precedente ya establecido
  por `web/reporte_cuarentena.py` (lectura sin HTML) y `web/plantilla_reporte.py` (render sin
  dependencias, CSS en línea, todo escapado).
- Rango de tiempo restante, nunca un número con falsa precisión.

### Fuera

- **Reestructurar el camino de producción para que atraviese la máquina de estados modelada.** Es
  trabajo futuro explícito, condicionado a saber cómo entregará el corpus el instituto.
- **Reanudación por documento a mitad de corrida.** Mismo cambio futuro, misma condición.
- Autenticación del panel, histórico entre corridas, gráficos de series temporales.

## Capacidades

### Capacidades nuevas

- `trazabilidad-por-corrida`: toda fila producida por una corrida es atribuible a ella y datable;
  el desenlace de cada documento inventariado es o publicado, o apartado, o explícitamente
  desconocido.
- `panel-de-operacion`: embudo por etapa, throughput y rango de tiempo restante, servidos sin
  dependencias de red y sin PII.

### Capacidades modificadas

- `portal-de-corridas`: el requisito "Consulta de progreso" pasa de estados agregados a embudo por
  etapa real con tiempo estimado, y exige una implementación de servicio y un proceso que sirva la
  aplicación (hoy no existe ninguno de los dos).
- `escritura-idempotente`: la garantía "reprocesar no duplica" hoy cubre la salida pero **no**
  cuarentena. Se extiende.

## El tiempo restante: un rango, y por qué

- **Cota optimista**: tasa de la ventana móvil reciente de documentos terminados. **Cota
  pesimista**: tasa promedio de todo el tiempo activo de la corrida. Se muestra el intervalo.
- **Los huecos de inactividad se excluyen.** La corrida admite pausa y reanudación; medir contra
  tiempo de pared subestima brutalmente el throughput y sobreestima el faltante.
- **Cuarentena cuenta como throughput**, con una excepción: un documento apartado en `ingesta` por
  sobretamaño no consumió trabajo (nunca se leyó su contenido, `ingesta/fuente.py:173-187`). El
  resto sí se extrajo y se parseó antes de caer.
- **Con menos de N documentos terminados no se muestra estimación**, se muestra "midiendo". El costo
  por documento no es uniforme —ECG, laboratorio y eco tienen costos de parseo y NER distintos— así
  que una proyección temprana miente.

## Invariantes

1. El panel **MUST NOT** mostrar ningún dato que no esté ya en tablas sin PII por diseño. Todo lo
   que salga del ejecutor hacia métricas o bitácora **MUST** pasar por `resumen_trazable()` y las
   listas blancas existentes.
2. El HTML servido **MUST NOT** referenciar `http://`, `https://` ni `<script src=...>` externo.
   Cero dependencias nuevas en `pyproject.toml`.
3. Cablear la observabilidad **MUST NOT** alterar el aislamiento de fallo por documento: un fallo
   del colector o de la bitácora no puede tumbar el procesamiento de un documento.
4. La suma `publicados + apartados + sin desenlace + en vuelo` **MUST** ser igual a los
   inventariados. Si no cierra, el panel lo dice en vez de repartir la diferencia.
5. La web sigue siendo adaptador: el núcleo **MUST NOT** importar nada de `web/`.

## Salvaguarda contra la cuarta pieza huérfana

Un test centinela de cableado, en la línea de `tests/carga/test_cableado_del_banco.py:29` y
`tests/integracion/test_wiring_produccion.py`: procesa un grupo real **por
`construir_fabrica_ejecutor`**, la raíz de composición de producción, con un colector espía, y falla
si no recibió observaciones. No inspecciona código fuente por texto: ejercita el camino real. Si
alguien quita la inyección, el test se pone rojo.

Regla que este cambio deja asentada: **ninguna pieza de observabilidad se declara terminada sin un
test que la ejercite por la raíz de composición de producción.**

## Riesgos

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| `corrida_id` se filtra al núcleo como concepto de infraestructura | Media | Viaja como dato en `ItemLote` y en el registro, no como dependencia; el núcleo no consulta corridas |
| La migración rompe en SQLite | Media | `op.batch_alter_table` para FK y unicidad; el mismo esquema corre en SQLite (tests) y Postgres (producción) |
| Cablear métricas cambia el tiempo por documento medido en los ensayos de carga | Baja | Colector en memoria, sin E/S en el camino caliente; se revalidan los ensayos de mil y diez mil |
| El residuo "sin desenlace" asusta al operador | Media | Se rotula y explica en la pantalla; es información, no ruido |
| `corrida_cerrada=False` en el futuro rompe el cierre aritmético del embudo | Baja hoy | Centinela sobre la invariante 4 |

## Criterio de éxito

- [ ] Con una corrida en marcha, el panel muestra en menos de dos segundos cuántos documentos
      pasaron cada etapa, dónde se cayeron y con qué código.
- [ ] La suma del embudo cierra contra los inventariados en el ensayo de diez mil.
- [ ] Reprocesar una corrida no cambia ningún conteo del embudo.
- [ ] El panel se sirve desde un proceso real, no desde un test.
- [ ] El centinela de observabilidad se pone rojo si se quita la inyección.
- [ ] La página no referencia ninguna URL externa (test existente).

## Plan de reversión

Dos capas separables. La web y el cableado de observabilidad se revierten con el código: nada
depende de ellos. El esquema requiere `downgrade` de la migración; las columnas nuevas son
opcionales y sin relleno hacia atrás —mismo criterio que `estudio.clave_documento`— así que las
filas escritas antes conviven sin romper nada, y revertir sólo devuelve al estado actual de no
poder agrupar por corrida. No hay pérdida de datos clínicos ni necesidad de reprocesar.

## Impacto en las pruebas existentes

- `tests/web/test_rutas_corridas.py` usa `_ServicioFake`. Con implementación real, el fake se
  conserva para las rutas y se agregan pruebas de integración del servicio contra base real.
- Los oráculos de `tests/carga/` cuentan cuarentenas por código. La unicidad de cuarentena no debe
  cambiar el total en un corpus que se procesa una sola vez; si cambia, hay un reprocesamiento
  oculto que el oráculo no contemplaba y es un hallazgo, no un ajuste.
- `tests/integracion/test_reprocesar_no_duplica.py` se extiende a cuarentena, que hoy no cubre.
