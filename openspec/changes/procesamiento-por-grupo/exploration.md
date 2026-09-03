# Exploración: procesamiento por grupo

## El problema

La validación de completitud de episodio —que un paciente tenga sus estudios y que no haya
asociaciones ambiguas— **no corre en producción**. `EjecutorPipeline` recibe
`coordinar_episodios=None` por defecto y en ese modo `_coordinar_resueltos` devuelve una lista
de fallos vacía: no se aparta ningún documento.

Ningún llamador de producción lo inyecta: ni `scripts/procesar_carpeta.py` ni
`construir_fabrica_ejecutor` en `trabajadores/tareas.py`.

Y no puede inyectarse tal cual. La tarea `procesar_documento` arma `procesar_lote([item])` —un
lote de UNO— y un lote de un documento nunca contiene los tres tipos requeridos, así que
activar el coordinador ahí mandaría el 100 % de los documentos a cuarentena. Verificado
experimentalmente.

## Tres comportamientos coexistiendo

| Camino | Modo | ¿Valida episodios? |
|---|---|---|
| Banco de carga (`tests/fixtures/corpus_piloto.py:175`) | lote completo | **Sí** — inyecta el coordinador |
| Script manual (`scripts/procesar_carpeta.py`) | lote de todo el directorio | No |
| Worker de producción (`trabajadores/tareas.py`) | lote de uno | No |

Ninguno de los tres es el modo que describe la máquina de estados. Y el banco de carga —del
que salen las cifras de cuarentena que la bitácora registra como evidencia— es el único que
valida.

## Por qué NO se construye la coordinación al cierre de corrida

Era la solución candidata. La exploración del terreno mostró que sale mucho más cara de lo
previsto y que, además, resuelve un problema que no vamos a tener.

**Lo que costaría.** La máquina de estados de corrida (`dominio/corridas.py`) es
enteramente declarativa: ningún código de `src/` instancia `Corrida` ni llama `avanzar_a`, y
`RepositorioCorridas` no tiene siquiera un método `actualizar_corrida`. Las tareas por etapas
`procesar_extraccion_minima` y `procesar_extraccion_completa` sí están implementadas, con
control optimista de versión, pero no las llama nadie y viven en una pista paralela que no se
comunica con `EjecutorPipeline`.

Peor: **`procesar_documento` no recibe `corrida_id`**. No existe registro de a qué corrida
pertenece un documento procesado, de modo que ni siquiera se podría agrupar qué coordinar al
cierre.

Y no hay dónde esperar: la escritura a Postgres es inmediata y definitiva. `episodio` y
`estudio` no tienen columna de estado, no hay concepto de borrador ni área de retención. Si la
validación llegara al cierre, los documentos de un episodio incompleto ya estarían publicados y
habría que retractarlos.

**Por qué además no hace falta.** El instituto no va a entregar documentos sueltos. El
codirector médico lo dijo explícitamente: van a ser cientos de miles de agrupaciones de cuatro
PDFs, y cada agrupación es un paciente.

Si la unidad de trabajo es el grupo y no el documento, el coordinador —que ya existe y ya
funciona— recibe todo lo que necesita en un solo lote. Sin máquina de estados, sin
`corrida_id`, sin área de retención, sin publicar y después retractar.

La coordinación al cierre es la solución correcta cuando los documentos llegan sueltos y
desordenados. No es el caso.

## Riesgo asumido

La estructura de carpetas es una promesa del codirector, no una especificación firmada. Si el
material terminara llegando suelto, este cambio no alcanza y habría que construir la
coordinación al cierre de todos modos.

Se acepta el riesgo porque el trabajo no se tira: procesar por grupo es la forma correcta de
expresar "estos documentos deberían formar un episodio" venga como venga el material, y el
coordinador degrada bien — un grupo incompleto va a cuarentena con su motivo.

## Los códigos de cuarentena son ambiguos

`COBERTURA_AMBIGUA` y `COBERTURA_INCOMPLETA` tienen **dos productores cada uno**:

| Código | Nivel episodio (coordinador) | Nivel campo (reconciliación) |
|---|---|---|
| `COBERTURA_AMBIGUA` | asociación ambigua: `pipeline/ejecutor.py:79` | campo con más de una fuente: `reconciliacion/inventario.py:37,42` |
| `COBERTURA_INCOMPLETA` | faltan estudios: `pipeline/ejecutor.py:80` | campo no verificable: `inventario.py:48,54`, `laboratorio_general.py:199,212` |

Y `etapa` no los distingue: `Etapa.RECONCILIACION.value` y `EtapaDocumento.RECONCILIACION.value`
son el mismo string `"reconciliacion"`.

Hoy se pueden separar sólo por una convención implícita: el coordinador nunca completa `campo`
ni `pagina`, la reconciliación siempre los completa. Inferir "nivel episodio" de que `campo` sea
nulo es frágil — cualquier productor futuro que rompa esa convención lo arruina en silencio.

Son **dos problemas operativos distintos**. "A este paciente le falta el ecocardiograma" se
resuelve pidiéndoselo a cómputos; "no pude verificar el potasio contra el PDF" es un problema
del parser. Quien lea el reporte de cuarentena para decidir qué hacer necesita distinguirlos.

## Áreas afectadas

- `src/anonimizacion/trabajadores/tareas.py` — la unidad de trabajo y la raíz de composición
- `src/anonimizacion/pipeline/ejecutor.py` — el mapeo motivo → código de cuarentena
- `src/anonimizacion/dominio/errores.py` — códigos nuevos
- `src/anonimizacion/pipeline/coordinador_episodios.py` — sin cambios de lógica previstos
- `scripts/procesar_carpeta.py` — hoy corre en lote sin coordinador
- `tests/pipeline/test_modo_sin_validacion_de_episodio.py` — su centinela describe el estado
  que este cambio corrige
- `tests/carga/` — los oráculos enumeran cuarentenas por código

## Riesgos

- **Los oráculos de carga cambian.** Separar los códigos redistribuye los conteos por código.
  El total debe permanecer idéntico: si cambia, es un bug, no un efecto esperado del cambio.
- **El centinela de `coordinar_episodios=None`.** El default del ejecutor puede quedarse en
  `None`; lo que cambia es que la fábrica de producción sí lo inyecte. Conviene mantener el
  default y el centinela, y que el contrato nuevo se exprese sobre la fábrica.
- **El invariante de la cola.** Un mensaje por grupo transporta varias referencias, no una. No
  debe transportar contenido ni PII: sigue siendo un conjunto de `{id_documento, uri, sha256}`.
- **`scripts/procesar_carpeta.py`** procesa el directorio entero como un lote. Con el
  coordinador activo, un directorio con muchos pacientes se agrupa por ancla igual que antes,
  así que su comportamiento cambia: pasa a validar. Hay que decidir si eso es deseable (creo que
  sí) y dejarlo explícito.

## Fuera de alcance

- La coordinación al cierre de corrida y la máquina de estados de corrida.
- Cinecoronariografía.
- Que el banco de carga use la fábrica de producción: depende de este cambio y va después.

## ¿Listo para propuesta?

Sí.
