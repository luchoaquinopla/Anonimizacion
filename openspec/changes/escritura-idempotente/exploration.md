# Exploración: escritura idempotente

## El problema, reproducido

Escribir el mismo `RegistroAnonimizado` tres veces produce tres filas:

```
filas en estudio      : 3
filas en medicion_ecg : 3
```

No es una hipótesis derivada de leer el código: es el resultado de correr
`EscritorPostgres.escribir_registro` tres veces sobre el mismo registro contra SQLite en
memoria.

## Por qué importa en este proyecto y no en cualquiera

El anonimizador lo va a ejecutar el codirector médico sobre el corpus institucional completo
—del orden de cientos de miles de documentos, unos 5 TB— durante horas. Una interrupción y un
reintento no son un escenario hipotético: son una certeza operativa. El pipeline ya tiene
reanudación durable de corridas precisamente porque se asume que una corrida se corta.

Y el fallo es **silencioso**. Nada se rompe, ningún test falla, ninguna métrica se dispara: el
dataset simplemente termina con N copias del mismo estudio. Un modelo entrenado sobre eso
queda sesgado hacia los documentos que tocó reprocesar, sin que nadie lo note.

## Qué es idempotente hoy y qué no

| Escritura | Idempotente | Mecanismo |
|---|---|---|
| `escribir_episodio` | Sí | `sesion.get(Episodio, id_episodio)` y retorna si existe |
| `registrar_vinculo` | Sí | Compara el vínculo existente antes de escribir (`resolutor_claves.py`) |
| `documento_corrida` | Sí, **sólo dentro de una corrida** | `UniqueConstraint("corrida_id", "huella_contenido")` |
| `medicion_ecg` | **No** | Inserta siempre |
| `resultado_laboratorio` | **No** | Inserta siempre, una fila por analito |
| `medicion_eco` / `texto_seccion_eco` | **No** | Insertan siempre |
| `estudio` | **No** | Inserta siempre |
| Parquet | **No** | Anexa al dataset particionado |

La idempotencia de `documento_corrida` es por corrida: una segunda corrida sobre el mismo
corpus vuelve a insertar todo. Es exactamente el caso de "reprocesar después de un corte".

## La causa raíz: la identidad del documento se pierde en el camino

El documento tiene identidad desde la ingesta:

- `ArtefactoCrudo.sha256` — huella del contenido, calculada por bloques en `ingesta/fuente.py`.
- `ItemLote.id_documento` — identificador externo asignado en la ingesta, que viaja en el
  mensaje de cola junto con `uri` y `sha256`.

Pero `construir_registro` (`salida/constructor_registro.py:163`) recibe sólo
`(documento, claves, id_episodio, pepper, motor_pii)`. **Ni el `id_documento` ni el `sha256`
cruzan esa frontera**, y `RegistroAnonimizado` no tiene dónde guardarlos. El destino recibe un
registro sin ninguna forma de saber si ya lo escribió.

Ésa es la razón por la que el diseño del cambio `hora-de-estudio` dejó la idempotencia fuera de
alcance: no es plomería, falta un dato en el contrato.

## Decisión de identidad: derivada, no cruda

La clave estable no debe ser el `sha256` crudo. Publicar la huella del contenido en el dataset
de salida permitiría a cualquiera que tenga el PDF original confirmar que ese documento está en
el corpus — una prueba de pertenencia que el proyecto no quiere conceder, y que es justamente
la clase de vector que la pseudonimización busca cerrar.

El repositorio ya tiene el patrón resuelto: `pseudonimizacion/claves.py` deriva todos los
identificadores con `_hmac_hex(pepper, mensaje)` (`generar_id_paciente`, `generar_id_episodio`,
`generar_id_medico`, ...). La clave de documento debe seguir esa misma convención: un HMAC del
`sha256` con el pepper. Estable entre corridas, no reversible, y coherente con el resto del
esquema.

## Áreas afectadas

- `src/anonimizacion/pseudonimizacion/claves.py` — derivación de la clave de documento
- `src/anonimizacion/dominio/modelos.py` — `RegistroAnonimizado` debe transportarla
- `src/anonimizacion/salida/constructor_registro.py` — la frontera donde hoy se pierde
- `src/anonimizacion/pipeline/ejecutor.py:424` — el único llamador real de `construir_registro`,
  que sí tiene a mano el `id_documento` y el artefacto
- `src/anonimizacion/salida/modelos_orm.py` — restricción de unicidad
- `src/anonimizacion/salida/destinos/postgres.py` — escritura condicional
- `src/anonimizacion/salida/destinos/parquet.py` — el caso más difícil (ver riesgos)
- `migrations/versions/` — columna y restricción nuevas
- `tests/carga/` — oráculos de igualdad estricta

## Riesgos

- **Parquet no tiene restricciones de unicidad.** Un dataset particionado por tipo y año se
  anexa; no hay forma de "insertar si no existe" sin leer lo ya escrito. Es una decisión de
  diseño abierta: deduplicar al escribir, deduplicar al leer, o declarar el dataset como
  append-only y resolver la duplicación aguas abajo.
- **Reprocesamiento legítimo con contenido cambiado**: si un mismo documento se corrige y se
  vuelve a procesar, su `sha256` cambia y la clave también, así que se escribiría como un
  documento nuevo. Hay que decidir si eso es correcto (probablemente sí: es otro contenido) y
  dejarlo explícito.
- **El laboratorio escribe N filas por documento** (formato entidad-atributo-valor). La unicidad
  no puede ser por fila de resultado: tiene que anclarse en el documento, no en el analito.
- **Retroactividad**: las filas ya escritas no tienen clave de documento. La columna nace
  opcional y sin relleno hacia atrás, igual que se hizo con `id_estudio`.

## Fuera de alcance

- La coordinación al cierre de corrida (pendiente aparte, ya diagnosticado).
- Cinecoronariografía.
- Cualquier cambio en el mecanismo de ingesta.

## ¿Listo para propuesta?

Sí.
