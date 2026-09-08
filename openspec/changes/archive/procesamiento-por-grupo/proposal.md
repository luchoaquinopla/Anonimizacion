# Propuesta: procesamiento por grupo

## Intención

Que la validación de completitud de episodio corra en producción, y que un problema de episodio
sea distinguible de uno de campo en el reporte de cuarentena.

## El problema

La validación de episodio existe, está probada, y **no corre en producción**. `EjecutorPipeline`
recibe `coordinar_episodios=None` por defecto y en ese modo no aparta ningún documento. Ningún
llamador de producción lo inyecta.

No puede inyectarse tal cual: `procesar_documento` arma un lote de UN documento, y un lote de uno
nunca contiene los tres tipos requeridos, así que activar el coordinador ahí mandaría el 100 % a
cuarentena. Verificado experimentalmente.

Hoy conviven tres comportamientos: el banco de carga valida, el script manual no, y el
trabajador tampoco. Las cifras de cuarentena que la bitácora registra como evidencia salen del
único de los tres que valida.

## La solución, y por qué no la otra

**La unidad de trabajo pasa a ser el grupo.** El instituto entregará cientos de miles de
agrupaciones de cuatro PDFs, una por paciente. Si el lote es el grupo, el coordinador recibe en
una sola pasada todo lo que necesita, y ya funciona sin tocarlo.

Se descartó construir la coordinación al cierre de corrida. Costaría mucho más —la máquina de
estados de corrida es enteramente declarativa, `procesar_documento` ni siquiera recibe
`corrida_id`, y no hay área de retención, así que habría que publicar y después retractar— y
resuelve un problema que no vamos a tener: los documentos no llegan sueltos.

## Alcance

### Dentro

- La tarea de cola pasa a recibir el grupo. El mensaje transporta sólo referencias.
- `construir_fabrica_ejecutor` inyecta el coordinador de episodios.
- Códigos de cuarentena propios para el nivel episodio, separados de los de nivel campo.
- El script manual se construye por la misma raíz de composición.

### Fuera

- La coordinación al cierre de corrida y la máquina de estados de corrida.
- Cinecoronariografía.
- Que el banco de carga use la fábrica de producción: depende de este cambio y va después.

## Invariantes

1. El mensaje de cola **MUST** transportar sólo referencias, nunca contenido ni datos
   identificatorios.
2. El total de documentos apartados en el ensayo de mil **MUST** seguir siendo 26. Sólo cambia
   el reparto por código. Un cambio en el total es un defecto.
3. No **MUST** quedar ningún camino de producción sin validación de episodio.

## Criterio de éxito

- Un grupo incompleto procesado por la fábrica de producción se aparta entero y no publica nada.
- Un problema de episodio y uno de campo llevan códigos distintos, sin depender de que un campo
  quede vacío.
- Los ensayos de mil y diez mil conservan su total de apartados y su composición general.

## Predicción falsable

El diseño sostiene, por aritmética sobre la composición del corpus sintético, que **las 25
cuarentenas de cobertura del ensayo de mil son todas de nivel episodio y ninguna de nivel
campo**. Si al correr el ensayo con los códigos separados sobrevive algún `cobertura_*`, esa
aritmética está mal y existe un productor de nivel campo que el oráculo no contemplaba.

Se deja escrito para que el resultado del ensayo confirme o refute la afirmación, en lugar de
ajustarse a ella.

## Plan de reversión

No toca el esquema: los códigos de cuarentena se persisten como texto plano, así que no hay
migración. Revertir es volver a no validar en producción — un estado peor pero conocido, sin
pérdida de datos ni necesidad de reprocesar.

## Impacto en las pruebas existentes

- `tests/integracion/test_wiring_produccion.py` procesa UN documento y espera éxito. Con el
  coordinador inyectado por la fábrica, **se vuelve rojo por diseño**: hay que migrarlo a un
  grupo completo. Es el efecto buscado, no una regresión.
- `tests/pipeline/test_modo_sin_validacion_de_episodio.py` es un centinela que fija el default
  `None` del ejecutor. Ese default se conserva —la política vive en la fábrica, no en el
  núcleo—, pero el centinela describe un estado que este cambio corrige y debe reescribirse
  deliberadamente, con un centinela inverso sobre la fábrica.
- Los oráculos de `tests/carga/` cambian el reparto por código, nunca el total.
