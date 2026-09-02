# Propuesta: escritura idempotente

## Intención

Que procesar dos veces el mismo documento no agregue nada la segunda vez, y que publicar un
episodio conserve todos sus documentos.

Hoy ninguna de las dos cosas se cumple, y ambas fallan en silencio.

## Los dos defectos, reproducidos

**Duplicación al reprocesar.** Escribir el mismo `RegistroAnonimizado` tres veces produce tres
filas en `estudio` y tres en `medicion_ecg`. `escribir_episodio` y `registrar_vinculo` sí son
idempotentes; las mediciones y `estudio` no.

**Pérdida al publicar.** `PublicadorBundles.publicar` recorre los registros del episodio y llama
`EscritorParquet.escribir_episodio` una vez por documento. Ese método escribe la tabla a un
temporal y hace `replace` sobre el archivo del episodio, o sea **sobrescribe**. De un episodio
con tres estudios sobrevive uno solo. No es al republicar: es la primera vez.

## Por qué ahora

El anonimizador lo ejecutará el codirector médico sobre el corpus institucional completo
—cientos de miles de documentos, unos 5 TB— durante horas. Que una corrida se interrumpa y haya
que retomarla es una certeza operativa, no una hipótesis: el pipeline ya tiene reanudación
durable justamente por eso. Pero esa idempotencia es **por corrida**; una corrida nueva sobre el
mismo corpus reinserta todo.

Y ninguno de los dos defectos se nota. Nada se rompe, ningún test falla, ninguna métrica se
dispara. El conjunto de datos simplemente queda con copias de más o con estudios de menos, y
cualquier modelo entrenado encima hereda ese sesgo sin que nadie lo advierta. En una
investigación clínica, un error silencioso es peor que uno ruidoso.

`PublicadorBundles` no tiene llamador de producción todavía, así que su defecto nunca produjo
datos. Corregirlo ahora cuesta dos tests; corregirlo con el conjunto de datos ya poblado exigiría
detectar qué estudios faltan y reprocesarlos.

## Alcance

### Dentro

- Clave estable de documento, derivada por HMAC del `sha256` con el pepper, propagada desde la
  resolución del documento hasta ambos destinos.
- Restricción de unicidad en `estudio` y escritura condicional en Postgres.
- Corrección de `PublicadorBundles` y de `EscritorParquet.escribir_episodio` para que un bundle
  conserve todos sus documentos.
- Migración `0007` con la columna y la restricción, aditiva y sin relleno hacia atrás.

### Fuera

- La coordinación al cierre de corrida (pendiente aparte, ya diagnosticado).
- Cinecoronariografía.
- Cambios en el mecanismo de ingesta o en el contrato de la cola.
- Reprocesar tras mejorar un parser: la clave es del contenido, no de la versión del código, así
  que lo ya escrito no se actualiza solo. Requiere purga explícita, y no se resuelve acá.

## Invariantes

1. La clave de documento **MUST** derivarse, nunca publicarse el `sha256` crudo. Publicar la
   huella del contenido permitiría a cualquiera que tenga el PDF original probar que ese
   documento está en el corpus — la clase de vector que la pseudonimización cierra.
2. El mensaje de cola **MUST** seguir siendo exactamente `{id_documento, uri, sha256}`, y
   `ArtefactoCrudo` no transporta contenido.
3. La unicidad **MUST** anclarse en el documento, no en la fila. `resultado_laboratorio` es
   entidad-atributo-valor: una restricción por analito no expresa la garantía buscada.
4. La columna nace opcional y sin relleno hacia atrás, igual que `id_estudio` en la migración
   `0006`.

## Criterio de éxito

- Procesar N veces el mismo documento deja exactamente una fila en `estudio` y un conjunto de
  mediciones, verificado por test.
- Publicar un episodio de tres documentos conserva los tres, verificado por test.
- Republicar un episodio no agrega ni pierde nada.
- Los oráculos de igualdad estricta de `tests/carga/` siguen validando, y los ensayos de 1.000 y
  10.000 no muestran regresión.

## Plan de reversión

El cambio se entrega en dos unidades con costos de reversión distintos.

La primera —clave de documento en el dominio, propagación y corrección del publicador— se
revierte sin pérdida: no toca el esquema y el publicador vuelve a su comportamiento anterior,
que es defectuoso pero conocido.

La segunda —columna y restricción de unicidad— sí toca el esquema. El `downgrade` descarta las
claves de documento ya persistidas, con lo cual se pierde la capacidad de reconocer un
reprocesamiento, pero no se pierde ningún dato clínico: las mediciones, los episodios y los
estudios sobreviven intactos. Recuperar la capacidad exige volver a aplicar la migración y
reprocesar para repoblar la columna.

## Impacto en las pruebas existentes

- Cambiar la firma de `EscritorParquet.escribir_episodio` rompe `tests/salida/test_publicador_bundles.py`.
  Es deliberado: dejar un método que pierde documentos en silencio es peor que actualizar un test.
  (Corrección sobre una versión previa de esta propuesta: `tests/integracion/test_momento_estudio_ambos_destinos.py`
  **no** se ve afectado — sus llamadas a `escribir_episodio` son de `EscritorPostgres`, y para Parquet
  usa `escribir()`.)
- Pasar la clave como argumento obligatorio de `construir_registro` toca las tres compuertas de
  `tests/calibracion/`, una línea cada una. Se eligió argumento obligatorio antes que un valor por
  defecto silencioso, para que ningún llamador nuevo pueda omitirla sin que el tipo lo señale.
- Los oráculos de `tests/carga/` verifican composición del corpus, no esquema, así que no deberían
  romperse. Se revalidan igual.
