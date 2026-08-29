# Propuesta: hora del estudio

## Intención

El delta temporal entre ECG y laboratorio es una **variable de investigación** del proyecto, no un metadato. Hoy el pipeline no puede producirlo, y no por falta de datos en el origen: el ECG captura `HH:MM:SS` en el header y `parseo/ecg_mortara.py:234` la trunca en la línea siguiente; el laboratorio captura `Hora de Extracción:` (`laboratorio_general.py:127`) pero la deja caer en el bolsón `adicionales`, sin tipo, sin normalización y sin `ReferenciaCampo` que la haga citable.

Corrección al `exploration.md`: el parser de laboratorio **sí** busca ya el campo. El trabajo no es extraerlo, es **promoverlo a dato de primera clase con procedencia**.

## Alcance

### Dentro de alcance
- Campo de hora **opcional** en `DocumentoParseado` y `RegistroAnonimizado`, separado de `fecha_estudio: date`.
- ECG: dejar de truncar la hora ya capturada (precisión de segundo).
- Laboratorio: promover `hora_extraccion` de `adicionales` a campo tipado (precisión de minuto).
- Ecocardiograma: emitir **ausencia explícita**; nunca un valor por defecto.
- Normalización de hora sin inferencia, en la línea de `normalizar_fecha_iso` ("sin inferir fechas").
- `ReferenciaCampo` propia para la hora en los tres reconciliadores.
- Persistencia: `modelos_salida.py`, `destinos/parquet.py`, `modelos_orm.py` y migración nueva.
- Actualizar `tests/calibracion/` (3 compuertas) y revalidar oráculos de `tests/carga/`.

### Fuera de alcance
- Cinecoronariografía: no hay muestra ni parser.
- **El cálculo del delta ECG↔laboratorio**: es consumo aguas abajo. Este cambio garantiza que el dato exista y sea confiable, nada más.
- Conversión o inferencia de zona horaria.
- Cualquier normalización o interpretación clínica de valores.

## Invariantes

1. **La ausencia viaja como ausencia** hasta la salida, distinguible de cualquier hora real. Ningún default de medianoche: fabricaría precisión inexistente en la variable que motiva el cambio.
2. **La hora es procedencia citable**, igual que el resto de los campos: la reconciliación MUST poder verificarla contra el documento fuente.
3. **Cero inferencia**: no se introduce ninguna fecha ni hora que no esté literalmente en el documento.
4. **Hora local del instituto**, sin conversión: los documentos no declaran huso; interpretarlo sería inventar el dato.

## Capacidades

### Capacidades nuevas
- `momento-del-estudio`: extracción, normalización, procedencia y persistencia del momento del estudio, con ausencia explícita por tipo de documento.

### Capacidades modificadas
- Ninguna. `openspec/specs/` está vacío (no hay specs consolidadas todavía).

## Enfoque

Ausencia explícita, ya decidida en la exploración: `fecha_estudio: date` se conserva y se agrega un campo de hora opcional. Migrar a `datetime` sería un error — el eco no trae hora y las 00:00 resultantes serían indistinguibles de una hora real.

Consecuencia aceptada: el delta ECG↔laboratorio tiene precisión de minutos; cualquier delta que involucre al eco queda limitado al día. Es coherente con la realidad clínica (el eco varía en semanas, no en horas), pero el consumidor MUST poder distinguir un caso del otro.

**Fork abierto para `sdd-design`**: hoy `medicion_ecg` y `resultado_laboratorio` **no guardan `fecha_estudio`** — sólo `id_episodio`, y `episodio.fecha_ancla` es por episodio (ventana ±7 días, varios estudios adentro). Sin una columna por estudio, el delta no es computable en SQL. Además `resultado_laboratorio` es EAV: una hora por fila es denormalizada. Dónde vive la columna es decisión de diseño, no de esta propuesta.

## Áreas afectadas

| Área | Impacto | Descripción |
|---|---|---|
| `dominio/modelos.py` | Modificado | Campo de hora opcional en ambos dataclasses |
| `parseo/ecg_mortara.py` | Modificado | `_parsear_fecha` deja de descartar `HH:MM:SS` |
| `parseo/laboratorio_general.py` | Modificado | `hora_extraccion` sale de `adicionales` |
| `parseo/eco_doppler.py` | Modificado | Ausencia explícita |
| `reconciliacion/normalizacion.py` | Modificado | Normalización de hora sin inferir |
| `reconciliacion/` (por tipo) | Modificado | `ReferenciaCampo` de la hora |
| `salida/modelos_salida.py`, `constructor_registro.py`, `destinos/parquet.py` | Modificado | Propagación hasta la salida |
| `salida/modelos_orm.py`, `migrations/versions/` | Modificado | Columna nueva + migración |
| `tests/calibracion/` | Modificado | 3 compuertas uno a uno, campo por campo |
| `tests/carga/` | Modificado | Oráculos de igualdad estricta a revalidar |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| Un default de hora corrompe la variable de investigación | Media | Test que MUST fallar si el eco emite hora; ausencia verificada extremo a extremo |
| Confundir hora de extracción con fecha de recepción o con la columna de resultados anteriores | Media | Compuerta de calibración de laboratorio ancla el campo rotulado correcto |
| Las 3 compuertas de calibración son deliberadamente estrictas | Alta | Actualizarlas en el mismo work unit que el parser, nunca después |
| Oráculos de `tests/carga/` (1000 y 10000 PDFs) rompen por igualdad estricta | Alta | Regenerar y volver a correr ambos benchmarks |
| La columna SQL queda mal ubicada y hay que re-migrar | Media | Resolver el fork en `sdd-design` antes de escribir la migración |
| Zona horaria se interpreta en algún consumidor | Baja | Decisión documentada en la spec: hora local, sin huso |

## Plan de rollback

Revertir **no es barato**: hay migración de esquema, así que `git revert` del código MUST ir acompañado de un `downgrade` de Alembic. Costo real:

- **Código y Parquet**: `git revert` del rango de commits. El campo es aditivo y opcional, así que nada aguas arriba depende de él.
- **SQL**: la migración de bajada **borra la columna y los datos de hora ya escritos**. Si ya se procesó corpus, revertir significa reprocesarlo para recuperar el dato.
- **Mitigación**: separar en work units — (1) dominio + parseo + reconciliación + Parquet, (2) ORM + migración. El work unit 1 se revierte solo y sin pérdida; el 2 es el único con costo de datos.

## Dependencias

- Ninguna dependencia externa nueva. Alembic ya está en uso (migraciones `0001`–`0005`).

## Criterio de éxito

- [ ] `DocumentoParseado` y `RegistroAnonimizado` exponen la hora como opcional, y `fecha_estudio` sigue siendo `date`.
- [ ] Un ECG parseado conserva la hora al segundo; un test falla si vuelve a truncarse.
- [ ] Un laboratorio parseado expone la hora de extracción como campo tipado, y `adicionales` ya no la contiene.
- [ ] Un eco parseado emite ausencia de hora; **ningún** test acepta 00:00 como equivalente.
- [ ] Cada hora extraída tiene su `ReferenciaCampo` y la reconciliación la verifica contra el documento fuente.
- [ ] La ausencia sobrevive hasta Parquet y SQL como nulo, distinguible de cualquier hora real.
- [ ] Existe migración con `upgrade` y `downgrade` probados.
- [ ] Las 3 compuertas de `tests/calibracion/` verdes con el campo nuevo.
- [ ] `pytest` en verde y benchmarks de `tests/carga/` (1000 y 10000 PDFs) revalidados sin regresión.
