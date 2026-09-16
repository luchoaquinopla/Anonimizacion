# Diseño: auditoría y poda

Arquitectura de la cadena de siete entregas (E0–E6) de `proposal.md`. Este documento decide
el **cómo**: qué estructura toma cada arreglo, qué garantiza que nada retroceda, y dónde se
corta cada PR. No enumera tareas (eso es `tasks.md`).

> **Restricción rectora del usuario**: *"quiero que recubras con todos los tests necesarios
> para no romper el funcionamiento de lo ya construido, queremos mejorar no retroceder"*.
> Cuatro entregas tocan producción (E1, E2, E4, E5) y dos borran código. Todas las decisiones
> de abajo se ordenan por esa restricción; donde hubo que elegir entre elegancia y
> verificabilidad, ganó la verificabilidad.

Todo lo que este documento afirma sobre el código fue verificado leyéndolo. Lo que no se pudo
verificar está marcado como **supuesto**.

---

## D1 — Cómo se caracteriza el comportamiento actual sin congelar el defecto

### El problema, planteado con precisión

E1 **cambia comportamiento a propósito**: hoy `coordinador_episodios.py:128` usa
`set(tipos) != _TIPOS_REQUERIDOS`; mañana usará `_TIPOS_REQUERIDOS - set(tipos)`. Si un test de
E0 fija el comportamiento actual "tal cual", E1 lo rompe y parece regresión.

### Hallazgo que reencuadra la decisión (verificado)

Los tres defectos de E1 son, **hoy, no observables**. No es una opinión: es una propiedad del
universo de entradas alcanzable.

| Defecto | Por qué hoy no es observable |
|---|---|
| `coordinador_episodios.py:128` | `TipoDocumento` tiene exactamente 3 miembros y `_TIPOS_REQUERIDOS` son esos 3. Entonces `set(tipos) ⊆ _TIPOS_REQUERIDOS` **siempre**, y para subconjuntos `A ⊆ B`: `A != B ⟺ B - A ≠ ∅`. Las dos expresiones son **idénticas** sobre toda entrada alcanzable hoy |
| `salida/destinos/postgres.py:386-391` | La whitelist de `:320-325` rechaza con `ValueError` cualquier tipo que no sea LABORATORIO/ECG/ECOCARDIOGRAMA **antes** de llegar al despacho. Descartados los dos primeros por `if`/`elif`, el `else` sólo puede ser ECOCARDIOGRAMA. El `else` mudo es correcto hoy y sólo miente cuando se agrega un tipo a la whitelist |
| `salida/constructor_registro.py:231-246` | Ya termina en `else: raise ValueError(...)`. No hay falla silenciosa: hay un idioma distinto al de `parseo/registro.py` y `reconciliacion/registro.py`. El cambio a registry debe **preservar `ValueError`**, no convertirlo en `KeyError` |

**Consecuencia de diseño**: E1 es, sobre el universo de hoy, un refactor de comportamiento
idéntico. El cambio semántico sólo existe en un universo donde hay un 4to tipo — universo que
hoy **no se puede construir sin fabricarlo en el test**.

### Decisión

**Regla estructural, no lista de permisos**:

> Los tests de caracterización de E0 se escriben **exclusivamente sobre el universo de entradas
> alcanzable en `main`**: los tres `TipoDocumento` reales. Cualquier test que ejercite un 4to
> tipo simulado **no es caracterización**: es el test de corrección de E1, y vive en E1.

Con esa regla el conflicto desaparece por construcción: ningún test de E0 puede observar el
cambio de E1, porque ningún test de E0 puede construir la entrada que lo hace visible. No hay
que "permitirle" a E1 romper nada — no hay nada que romper.

Dos refuerzos baratos encima:

1. **Marcador `caracterizacion`** (`pyproject.toml`, `[tool.pytest.ini_options] markers`), en
   todos los tests de E0. No cambia la ejecución; hace que `-m caracterizacion` sea un
   conjunto nombrable y que un revisor vea de inmediato de qué tipo de test se trata.
2. **Acta de cambio intencional** en el cuerpo del PR de E1, de una línea por defecto,
   escrita **antes** de tocar código: *"un episodio con los 3 tipos requeridos más un 4to tipo
   deja de caer en `ESTUDIOS_FALTANTES`"*. Es la única divergencia semántica declarada de toda
   la cadena. Si durante E1 aparece una segunda, es señal de alto: se revisa antes de seguir.

### Segunda regla, igual de importante: caracterizar la superficie, nunca la estructura

Un test de caracterización que se rompe en E1–E5 estaba **mal escrito**, no revela regresión.
Por eso E0 afirma sólo sobre lo observable desde afuera:

| Área | Se afirma sobre | **No** se afirma sobre |
|---|---|---|
| Punta a punta | Filas en las tablas (`estudio`, `resultado_laboratorio`, `cuarentena`, `vinculo_paciente`), su conteo y sus campos no-PII | Qué módulo las escribió |
| Contrato del CLI | Banderas aceptadas por subcomando, defaults efectivos, códigos de salida | `_cargar_script`, `sys.argv`, el doble `argparse` |
| Códigos de cuarentena | Par `(entrada) → (CodigoErrorDocumento, etapa)` | La clase que lo lanzó |
| Embudo | La tupla de etapas y el desglose para un corpus fijo | Cómo se construye `ETAPAS_EMBUDO` |
| Reporte de corrida | Texto/estructura de salida que hoy alimenta `MetricasDespacho` | `observabilidad/metricas.py` |

Esto es lo que hace que **el mismo archivo de E0 sobreviva intacto a E4**, que es la entrega
que más mueve código. Si hubiera que editar los tests de E0 en E4, la red de seguridad dejaría
de serlo exactamente cuando más hace falta.

### Ritual de honestidad (criterio de aceptación de E0, no un extra)

Cada test de caracterización se valida **rompiendo a propósito** lo que dice proteger y
comprobando el rojo. La evidencia (mutación aplicada + salida en rojo) se pega en el PR de E0.
Forma concreta de la mutación, una por área: invertir el `!=` del coordinador; cambiar el
`else` de `postgres.py` a `_escribir_ecg`; sacar `"despacho"` de `ETAPAS_EMBUDO`; cambiar un
default de `argparse`; eliminar un contador del reporte de corrida.

**Alternativas descartadas**

- *Congelar el comportamiento actual literal y marcar los tests afectados como
  "caracterización-de-defecto"*. Descartada: presupone que hay tests de E0 que E1 rompe, y el
  análisis de arriba muestra que no los hay. Habría que **fabricar** un test que observe el
  defecto (con un 4to tipo) sólo para después marcarlo como esperado-a-cambiar: ceremonia sin
  información.
- *Lista blanca de comportamientos que E1 puede cambiar, escrita antes*. Descartada como
  mecanismo principal: es una promesa en prosa, no una garantía. Sobrevive rebajada a "acta de
  una línea" porque documentar la intención sigue teniendo valor para el revisor.
- *Snapshot testing (golden files) de la salida completa del pipeline*. Descartada: un golden
  file se actualiza con `--snapshot-update` sin que nadie lea el diff; convierte la red de
  seguridad en un trámite. Se prefieren aserciones escritas a mano sobre las filas que
  importan.

### Aislamiento de la base (obligatorio, defecto verificado en la suite actual)

`tests/integracion/test_postgres_carrera_real.py:98` hace `Base.metadata.drop_all(engine)`
sobre la base **compartida** `anonimizacion` del puerto 5433. Ese patrón **no se replica** en
E0. Las fixtures de caracterización punta a punta:

1. Abren una conexión en `AUTOCOMMIT` a la base de mantenimiento (`postgres`) del mismo
   servidor.
2. `CREATE DATABASE caracterizacion_<uuid4.hex[:12]>`.
3. Crean el esquema ahí, corren, y `DROP DATABASE` en el teardown (con `finally`).
4. `pytest.skip` si no hay servidor, igual que el fixture existente.

Costo: ~1 s por creación/destrucción de base vacía (**supuesto**, no medido en esta máquina).
Beneficio: E0 se puede correr en paralelo con un colega trabajando y no le borra nada.

---

## D2 — Cómo se prueba el CLI instalado por wheel (E4)

### Hallazgo que cambia el test obvio (verificado)

El test "construir wheel, instalar, correr `anonimizacion --help`" **no detecta el defecto
actual**. `main()` (`cli.py:318-334`) despacha por subcomando, y `_cargar_script` sólo se
invoca dentro de `_comando_procesar` (`cli.py:204`) y `_comando_servir` (`cli.py:296`), después
de `diagnosticar`. Con `--help`, `argparse` termina el proceso antes de tocar nada. Peor:
`anonimizacion procesar --entrada X` tampoco llega, porque `_reportar_diagnostico` devuelve
`False` sin Postgres y retorna `1` en `cli.py:201` — **antes** de `_cargar_script`.

Un test de wheel que sólo corre `--help` es un test que pasa hoy, con el defecto vivo. Sería
exactamente el modo de fracaso que el proposal advierte para E1, trasladado a E4.

### Decisión: wheel real + venv efímero con `--system-site-packages`, e invocación que **sí** llega a la composición

```
fixture de sesión (una sola vez por corrida):
  uv build --wheel                                  -> dist/anonimizacion-*.whl
  uv venv --system-site-packages <tmp>/venv_wheel
  uv pip install --no-deps --python <tmp>/venv_wheel <wheel>
```

`--no-deps` + `--system-site-packages` es lo que hace que esto cueste segundos y no minutos:
spaCy, Presidio, PyMuPDF, SQLAlchemy y pyarrow se resuelven desde el entorno de desarrollo ya
instalado; sólo `anonimizacion` se instala de verdad. Sin red.

Tres tests sobre esa fixture:

1. **Guarda de honestidad** (primero, porque sin esto los otros dos no prueban nada). Un
   subproceso del venv imprime `anonimizacion.__file__` y `shutil.which("anonimizacion")`; el
   test afirma que **ambos caen dentro del venv efímero** y **ninguno** dentro del checkout.
   Sin esta guarda, un `.pth` de instalación editable en el site-packages heredado podría hacer
   que el test esté ejercitando el checkout y pase por el motivo equivocado. *(El
   site-packages del venv precede al heredado en `sys.path`, así que se espera verde;
   la guarda existe para que si algún día deja de ser cierto, el test lo diga.)*
2. **Empaquetado**: el `RECORD`/lista de archivos del wheel contiene los módulos nuevos de
   comandos y **ningún** `scripts/`. Test estático, milisegundos.
3. **El que detecta el defecto**: subproceso en el venv que ejecuta un `-c` corto —
   neutraliza `diagnosticar` (devolviendo hallazgos OK) y el `ejecutar` real (stub que
   devuelve `0`), y llama `anonimizacion.cli.main(["procesar", "--entrada", <tmp>, "--db-url",
   "postgresql://x/y"])`. Afirma código de salida `0` y que el stub fue invocado. **Hoy este
   test falla** con el error de `_cargar_script` sobre un `scripts/` inexistente: es el rojo
   que exige el proposal. Después de E4 pasa porque la composición vive dentro del paquete.
   No toca Postgres, no toca red, no carga spaCy.

Marcador `empaquetado` propio (además de los existentes). Corre en la suite por defecto —
`-m "not postgres"` lo incluye — porque su valor entero es correr sin que nadie se acuerde.

**Costo estimado**: `uv build` 3-6 s (hatchling, proyecto chico) + `uv venv` ~1 s + `uv pip
install --no-deps` ~1 s + 3 subprocesos ~1-3 s cada uno. **Del orden de 12-20 s por corrida
completa, una sola vez** (fixture de sesión). Es un **supuesto**: no se midió en esta máquina;
si en `sdd-apply` supera ~45 s se mueve a un marcador deseleccionable y se exige en CI.

**Alternativas descartadas**

- *Venv sin `--system-site-packages`, resolviendo dependencias de verdad*: instalar
  `es_core_news_lg` + Presidio + PyArrow son cientos de MB y minutos, con red. Inaceptable para
  la suite.
- *Descomprimir el wheel y poner la carpeta en `PYTHONPATH`, sin instalar*: barato y
  determinista, pero **no ejercita la generación del console script** de `[project.scripts]`,
  que es parte del contrato que IT usa. Se descarta como sustituto, aunque la técnica sobrevive
  dentro de la guarda de honestidad.
- *`pip install --no-deps` y verificar sólo que el entry point resuelve e importa*: no llega a
  la composición, no detecta el defecto (mismo error que `--help`). Descartada.
- *Marcarlo lento y correrlo aparte*: descartada como opción por defecto. El defecto de E4 es
  precisamente un defecto que la suite normal no ve; sacarlo de la suite normal reproduce la
  causa raíz. Queda como plan B medido, no como decisión.

---

## D3 — Dónde vive, después de E4, la lógica que hoy está en `scripts/`

### Verificación del riesgo de pickling (era la incógnita técnica más concreta)

`trabajadores/despacho_paralelo.py:1-38` documenta que `ProcessPoolExecutor` con `spawn`
picklea por **referencia de módulo**, y que una función definida en un módulo cargado por
`spec_from_file_location` **no es picklable** para el hijo (rompe el pool entero con
`BrokenProcessPool`). Verificado qué cruza realmente el límite de proceso:

- `initializer=inicializar_trabajador` (`despacho_paralelo.py:208, 298`) — módulo real de
  `anonimizacion`.
- `funcion_trabajo`, con default `procesar_grupo_en_trabajador` (`despacho_paralelo.py:665`),
  sometida en `:471` y `:532` — módulo real de `anonimizacion`.

`scripts/procesar_carpeta.py` aporta únicamente `crear_pool=lambda n: ...`
(`procesar_carpeta.py:208-214`), que es un **callable invocado en el proceso padre**
(`despacho_paralelo.py:531, 606, 628`): nunca se picklea. `engine` tampoco cruza (documentado
en `procesar_carpeta.py:302-307` y verificado: cada hijo arma el suyo desde `db_url`).

**Conclusión verificada: mover `scripts/` a `src/` no puede romper el pickling.** Es lo
contrario: el único artefacto no-picklable del repo es el módulo cargado por ruta, y E4 lo
elimina. `despacho_paralelo.py` no se modifica (no-objetivo), y su docstring sólo se comprime
en E6, cuando su advertencia ya sea historia.

### Decisión: paquete `src/anonimizacion/comandos/`

```
src/anonimizacion/
  cli.py                  # parser, resolución config+banderas, despacho. Nada más.
  comandos/
    __init__.py
    procesar.py           # ejecutar(), _despachar_grupos, _despachar_y_cerrar_corrida, ...
    servir.py             # construir_aplicacion(), servidor, apagado cooperativo
```

Reglas de corte:

- `cli.py` conserva **todo** el `argparse` y la resolución `bandera > archivo de configuración`
  (`_resolver`), y pasa **argumentos con nombre** a `comandos.procesar.ejecutar(...)` /
  `comandos.servir.servir(...)`. Desaparecen el segundo `argparse`, el monkeypatch de
  `sys.argv` y `_cargar_script`.
- `_DB_URL_DEFAULT` queda **sólo** en `configuracion.py:52`; `comandos/procesar.py` y
  `comandos/servir.py` lo importan de ahí. Las copias de `procesar_carpeta.py:80` y
  `servir_panel.py:107` mueren con el doble parsing que las justificaba.
- `_tipo_procesos` (validación del tope duro contra `despacho_paralelo.validar_grado_
  concurrencia`, hoy duplicada en ambos scripts) se aplica **una vez**, en el `argparse` de
  `cli.py`. Se preserva la propiedad que su docstring declara: el valor inválido falla con
  mensaje de `argparse` antes de tocar Postgres/spaCy.
- `ejecutar(...)` y `construir_aplicacion(...)` conservan su firma por palabra clave: los tests
  existentes las invocan directo y esa inyección (motor/engine) es lo que las hace testeables.

**Alternativas descartadas**

- *Todo dentro de `cli.py`*. `cli.py` ya tiene 339 líneas; absorbería ~860 más y llegaría a
  ~1.200. El composition root dejaría de ser legible de una sentada, y el parser quedaría
  enterrado entre lógica de corrida. Descartada.
- *`web/servidor_panel.py` para `servir` y `trabajadores/` para `procesar`*. Descartada por
  coherencia de capa: `web/` es la aplicación WSGI y `trabajadores/` es la ejecución; lo que se
  mueve es **composición de un subcomando**, que no es ninguna de las dos. `comandos/` nombra
  exactamente lo que contiene y hace obvio, al leer el árbol, que cada subcomando del CLI tiene
  un módulo.
- *Dejar `scripts/` y empaquetarlo en el wheel* (agregarlo a `packages`). Descartada: haría de
  `scripts/` un paquete importable sin serlo, conservaría el doble `argparse` y el monkeypatch
  de `sys.argv`, y mantendría el módulo-cargado-por-ruta que es el único artefacto no-picklable
  del repo.

### Destino de los tests (1.245 líneas)

`tests/scripts/test_procesar_carpeta.py` (705) y `test_servir_panel.py` (540) se mueven a
`tests/comandos/`, y su `_cargar_script`/`spec_from_file_location` se reemplaza por un `import`
normal. Es **simplificación**, no reescritura: el cuerpo de cada test no cambia.
`tests/test_configuracion.py:144-164` y los cinco `monkeypatch.setattr(cli, "_cargar_script",
...)` de `tests/test_cli.py` se adaptan a la nueva composición (mockear la función de comando
en vez del cargador). Se elimina la excepción `per-file-ignores` de `pyproject.toml:74-78` si
el import sin uso se va con la mudanza.

---

## D4 — Orden de presentación del embudo (E2)

### Hallazgo (verificado): el orden ya está decidido y documentado

`web/embudo_corrida.py:41-58` dice, textual, que la tupla es *"Orden de EJECUCIÓN real
(design.md, Decisión 8) — **NO** el orden del enum `Etapa`"*, explica por qué `despacho` va
justo después de `ingesta` (es el único punto donde un documento ya inventariado pudo
detenerse) y por qué `deteccion`/`deteccion_pii` quedan afuera (no producen cuarentena,
Requisito 2 de la spec).

### Decisión: el orden se preserva **verbatim** y se declara explícito

```python
# Orden de presentación del embudo -- decidido, no derivado del enum.
ORDEN_EMBUDO: tuple[EtapaPipeline, ...] = (
    EtapaPipeline.INGESTA,
    EtapaPipeline.DESPACHO,
    EtapaPipeline.EXTRACCION,
    EtapaPipeline.PARSEO,
    EtapaPipeline.RECONCILIACION,
    EtapaPipeline.COORDINACION,
    EtapaPipeline.PSEUDONIMIZACION,
    EtapaPipeline.SALIDA,
)
ETAPAS_EMBUDO: tuple[str, ...] = tuple(e.value for e in ORDEN_EMBUDO)
```

Motivo de **ese** orden y no otro: es el recorrido real de un documento, que es el único orden
bajo el cual el embudo **cierra aritméticamente** — `llegaron[n] = llegaron[n-1] -
apartados[n-1]`. Cualquier otro orden produce restas sin sentido y, según el propio comentario,
ya rompió el desglose una vez. Además es lo que el codirector médico viene mirando: cambiarlo
sería una decisión de producto disfrazada de refactor.

`deteccion` y `deteccion_pii` **siguen excluidas**: no producen cuarentena, así que una fila con
`llegaron = apartados = 0` sólo agregaría ruido a la vista.

Cómo se ataca la deriva sin endurecer tipos (per la "Corrección al análisis original" de la
propuesta, que este diseño acata: `ErrorDocumento.etapa` **sigue** aceptando `str | EtapaDocumento`):

1. **Fuente de verdad única de nombres**: `pipeline/etapas.py::Etapa` se amplía con `DESPACHO`
   y pasa a ser el vocabulario completo (10 miembros). `dominio/errores.py::EtapaDocumento` no
   cambia de forma ni de firma.
2. **Test de correspondencia** (`tests/pipeline/test_vocabulario_de_etapas.py`): recorre
   `src/` con `ast`, junta todas las asignaciones `_ETAPA = "..."` a nivel de módulo y afirma
   que cada valor es miembro del enum; y afirma que `{e.value for e in EtapaDocumento} ⊆
   {e.value for e in Etapa}`. Falla si alguien agrega una etapa de un solo lado. Es el test que
   hubiera atrapado `ejecutor.py:508`.
3. **Test de orden explícito**: afirma la tupla `ETAPAS_EMBUDO` literal, escrita a mano en el
   test. Si alguien reordena el enum, el embudo no se mueve; si alguien cambia el embudo a
   propósito, tiene que editar el test y el revisor lo ve. (Este test es el de caracterización
   de E0 — E2 no lo modifica, lo aprueba.)
4. **Test de cobertura del desglose**: todo miembro de `EtapaDocumento` está en `ORDEN_EMBUDO`
   **o** en una lista explícita de exclusiones (`DETECCION`, `DETECCION_PII`) con su motivo.
   Es lo que impide que una etapa nueva vuelva a caerse del desglose en silencio.

**Alternativas descartadas**: derivar el orden de la declaración del enum (le cambia la vista
al codirector médico y acopla presentación a declaración); un campo `orden: int` en cada miembro
del enum (mete presentación dentro del dominio y se desincroniza igual, sin ganar nada sobre
una tupla explícita).

---

## D5 — El test tautológico de equivalencia (E3)

### Lectura fina del archivo (verificada)

`tests/pipeline/test_equivalencia_agrupacion.py` no es uniformemente tautológico:

| Test | Aserciones |
|---|---|
| `..._un_episodio_completo` (:51) | **Sólo** la comparación tautológica `f(x) == g(x)`. Cero valor |
| `..._cortan_el_episodio_en_el_mismo_dia` (:64) | Tautológica **+** oráculo real a mano: `d1 == d2` (7 días entra), `d3 != d1` (8 días corta) |
| `..._no_dejan_derivar_la_ventana` (:81) | Tautológica **+** oráculo real: saltos encadenados de 6 días no se funden en 12 |
| `..._separan_pacientes_distintos` (:95) | Tautológica **+** oráculo real: pacientes distintos, episodios distintos |

O sea: hay tres oráculos independientes escritos a mano, tapados por una comparación que no
puede fallar. Y el `assert A == B` tautológico está **antes** del oráculo real en `:91` y
`:103`, con lo cual ni siquiera ayuda a diagnosticar.

### Decisión: **reemplazar, no eliminar** — y coincide con la inclinación del orquestador, por
una razón que el código confirma

La ventana de ±7 días es la regla de negocio central del proyecto (AGENTS.md, *"Requisito de
vinculación entre documentos"*). Se conserva el archivo, renombrado a
`tests/pseudonimizacion/test_ventana_de_episodio.py`, con:

1. Las comparaciones `_episodios_del_coordinador(x) == vincular_episodios(x)` **eliminadas**
   (junto con el helper `_episodios_del_coordinador` y `_pares`), porque
   `coordinador_episodios.py:86-103` delega en `vincular_episodios`: la igualdad es estructural.
2. Los tres oráculos existentes **conservados y reexpresados sobre `vincular_episodios`
   directamente**, que es la única implementación.
3. Oráculos nuevos escritos a mano, con fechas y agrupación esperada explícitas, sobre los
   bordes que hoy no se cubren: exactamente 7 días **antes** del ancla (simetría del ±), dos
   anclas del mismo paciente separadas por meses, y un episodio de un solo documento.
4. Aserciones sobre `metadata_por_episodio[...].fecha_ancla`, no sólo sobre qué documentos caen
   juntos: la fecha del ancla es parte del contrato y hoy nadie la afirma.
5. `coordinador_episodios.py:9-13` corregido: el docstring afirma que ese test *"fija esa
   equivalencia como contrato"* y eso dejó de ser cierto cuando el módulo pasó a delegar. Queda
   una línea que dice la verdad — que la ventana vive en `vincular_episodios` y acá sólo se
   traduce.

**Alternativa descartada**: eliminar el archivo con justificación escrita. Es defendible
formalmente (lo que prueba, lo prueba trivialmente) pero borraría tres oráculos reales que hoy
son la **única** cobertura escrita a mano de la regla clínica central. Se perdería capacidad de
detección en la entrega cuyo objetivo declarado es **recuperar** capacidad de detección.

### Los otros dos huecos de E3

- **31 tests sin oráculo en `tests/reconciliacion/`**. Verificado el contrato:
  `ReconciliadorDocumento.reconciliar` devuelve `tuple[str, ...]` con los `id_campo` que el PDF
  trae y el modelo no citó; **tupla vacía = documento completo** (`reconciliacion/base.py:26-35`).
  Entonces la aserción correcta y exigible es: `assert reconciliar(...) == ()` en los tests
  `test_aprueba_*`, y la **tupla exacta esperada** en los tests de degradación. Un
  `assert resultado is not None` no cumple el criterio de éxito de la propuesta y se rechaza en
  revisión.
- **Exhaustividad de códigos de cuarentena**. Test que afirma
  `{c.value for c in CodigoErrorDocumento} - {CAMPO_NO_EXTRAIDO} ⊆ EXPLICACION_POR_CODIGO.keys()`.
  `CAMPO_NO_EXTRAIDO` se excluye explícitamente porque, por su propio docstring
  (`dominio/errores.py:50-53`), nunca produce fila en `cuarentena` — la exclusión va con su
  motivo escrito, no como omisión.

---

## D6 — Estrategia de poda de comentarios (E6): el diff no puede cambiar el AST

### Decisión: compuerta mecánica `ast`-equivalente, archivo por archivo

Se agrega un test/utilidad **propio de E6** (`tests/prosa/test_poda_no_toca_codigo.py`):

```
para cada módulo de src/ tocado por el PR:
    arbol_antes  = ast.parse(contenido en la base del PR)
    arbol_despues= ast.parse(contenido en HEAD)
    assert normalizar(arbol_antes) == normalizar(arbol_despues)
```

donde `normalizar` = eliminar los docstrings (el `Expr(Constant(str))` inicial de módulo,
clase y función) y comparar `ast.dump(..., include_attributes=False)`, que ignora números de
línea y columna.

Por qué esto funciona y no es una promesa: **los comentarios `#` no existen en el AST** de
Python — el tokenizador los descarta —, así que borrarlos deja el árbol idénticamente igual.
Los docstrings **sí** existen (como `Constant`), y son justamente lo que E6 acorta: por eso se
los descuenta antes de comparar. Resultado: la compuerta pasa si y sólo si el diff tocó
**exclusivamente** comentarios y docstrings. Cualquier renombre, reordenamiento, cambio de
literal, import removido o línea "limpiada de paso" la pone en rojo, con el nombre del módulo.

Esto convierte *"no rompí nada"* de promesa en hecho verificable, y es más fuerte que la suite:
la suite prueba lo que se le ocurrió a alguien; esto prueba una propiedad de todo el diff.

Frontera declarada: `pyproject.toml` (los `noqa: C901` y su prosa) y `docs/pipeline.md` no son
Python parseable como módulo y quedan **fuera** de la compuerta; su revisión es humana y
explícita en el PR que los toque. Los `# noqa: C901` **en línea de `def`** sí están dentro:
borrarlos cambiaría el comportamiento de `ruff`, y aunque el AST no los vea, `ruff` en CI sí —
son doble red.

### Mecanismo de agrupación y orden

Agrupación **por capa**, no por tamaño ni alfabética: un revisor que abre "poda de `parseo/`"
tiene un solo contexto mental en la cabeza. Orden de menor a mayor riesgo de pérdida de
conocimiento, para que el criterio de poda se calibre en terreno barato antes de llegar al caro:

| # | Grupo | Riesgo |
|---|---|---|
| 1 | `dominio/`, `ingesta/` (salvo `lanzador_corrida.py`), `configuracion.py` | Bajo — prosa descriptiva |
| 2 | `extraccion/`, `deteccion/`, `parseo/` | Medio — hay calibraciones contra muestras reales |
| 3 | `reconciliacion/`, `pii/`, `pseudonimizacion/` | Medio |
| 4 | `salida/`, `pipeline/` | Medio |
| 5 | `web/`, `cli.py`, `docs/pipeline.md` | Bajo — pero acá va la prosa **falsa** (PR #40, módulo inexistente) |
| 6 | `trabajadores/despacho_paralelo.py` + `ingesta/lanzador_corrida.py` | **Alto** — concentran los invariantes medidos |

El grupo 6 va **solo y último**: `despacho_paralelo.py` tiene 364 líneas de docstring + 139 de
comentario y `lanzador_corrida.py` 328 de docstring; entre los dos están los 875 MB de RSS
medidos con ctypes, la semántica de `spawn`/pickling y el costo de recuperación ante un hijo
muerto. Merece un PR propio y una lectura humana sin nada más en el diff.

**Orden innegociable dentro de cada grupo: migrar a Obsidian primero, podar después.** La
migración es criterio de aceptación del PR, no un paso suelto; cada línea sobreviviente que
comprime un invariante lleva su puntero (`# 875 MB RSS por motor -- ver D-0XX en Obsidian`), y
el PR lista los punteros creados. Un PR de E6 sin entradas de Obsidian referenciadas se
rechaza aunque la compuerta AST esté verde: la compuerta prueba que no se rompió código, no que
no se perdió conocimiento.

**Alternativas descartadas**

- *Poda masiva en un solo PR con revisión de la suite*. La suite no protege prosa: pasaría
  verde con un invariante medido borrado. Descartada por el riesgo #1 de la propuesta.
- *Herramienta automática de recorte de docstrings a 2 líneas*. Cortaría por longitud, sin
  distinguir un párrafo de relleno de la medición de 875 MB. El criterio de esta entrega es
  semántico; no se automatiza.
- *Comparar tokens en vez de AST*. Los tokens **sí** incluyen `COMMENT`, así que habría que
  filtrarlos a mano y además cambiarían por el reflujo de líneas. El AST ya normaliza eso.
- *Comparar el bytecode compilado*. Equivalente en poder y mucho más opaco al fallar: un
  `assert` en rojo sobre `ast.dump` te dice qué nodo cambió; uno sobre `co_code` no.

---

## D7 — Presupuesto de tamaño por PR

Presupuesto del skill `chained-pr`: **400 líneas cambiadas** (`additions + deletions`) y ≤60 min
de revisión por PR. Estrategia fijada: `feature-branch-chain`, rama integradora
`feat/auditoria-y-poda` desde `origin/main` @ 6e22d9b, PR tracker en draft/no-merge.

```
main @6e22d9b
  └── feat/auditoria-y-poda  (tracker, draft, no-merge)
        └── PR0   E0  red de seguridad                        ~420  size:exception
              └── PR1   E1  trampas latentes                  ~180
                    └── PR2   E2  vocabulario de etapas       ~220
                          └── PR3   E3  poder de detección    ~300
                                └── PR4a  E4  mudanza procesar (rename-only + edits)  ~250*
                                      └── PR4b  E4  mudanza servir (rename-only + edits) ~200*
                                            └── PR5   E5  retiro Celery + métricas     ~350
                                                  └── PR6a..PR6f  E6 poda por capa
```

`*` con detección de renombres; ver abajo.

| PR | Presupuesto | Decisión |
|---|---|---|
| **PR0** | ~420 líneas, **todas nuevas** en `tests/caracterizacion/` | **`size:exception`**. Subdividir la red de seguridad sería peor: quedaría parcialmente tejida mientras PR1 ya la necesita entera, y el criterio de E0 ("no toca `src/`") se verifica de un vistazo sobre el diff completo. Es un PR de lectura rápida pese al tamaño: cinco archivos independientes, sin lógica de producción |
| **PR1** | ~180 | Cabe. Tres arreglos + tres tests con 4to tipo simulado. Un commit por defecto (3 unidades de trabajo) |
| **PR2** | ~220 | Cabe |
| **PR3** | ~300 | Cabe. Si las 31 aserciones de `tests/reconciliacion/` se pasan de 400, se parte en PR3a (oráculos de reconciliación) y PR3b (ventana de episodio + exhaustividad de códigos) |
| **PR4a / PR4b** | ~2.101 líneas brutas | **Se subdivide de verdad Y se estructura el diff.** Dos cortes: `procesar` y `servir`, que son independientes. Dentro de cada uno, **dos commits**: (1) `git mv` **puro**, sin una sola edición de contenido — GitHub y `git diff -M` lo muestran como renombre con 0 líneas cambiadas; (2) las ediciones reales (quitar `argparse`, `sys.argv`, `_DB_URL_DEFAULT`). El diff revisable queda en ~200-250 por PR. **Si la detección de renombres falla** (la edición del commit 2 dispara el umbral de similitud), se pide `size:exception` con el argumento de que el volumen es mudanza mecánica ya verificada por la suite que se mueve con ella |
| **PR5** | ~350 | Cabe. Incluye obligatoriamente `deploy/operacion-institucional.md:48-51` y quitar `celery`/`redis` de `pyproject.toml:18-19` |
| **PR6a–PR6f** | seis PRs, uno por grupo de D6 | Los grupos 1-5 entran o rozan el presupuesto; el **grupo 6** (`despacho_paralelo.py` + `lanzador_corrida.py`, ~800 líneas de borrado) pide **`size:exception`** con doble argumento: (a) es borrado puro de prosa, (b) la compuerta AST prueba mecánicamente que no se tocó código. Es el PR que más atención humana necesita y el que menos código cambia |

Reglas transversales de la cadena (del skill):

- Cada PR hijo lleva **diagrama de dependencias** con `📍` en el PR actual, y declara estado
  inicial, estado final, dependencias previas, trabajo posterior y fuera de alcance.
- `uv run pytest -q -m "not postgres"` verde en **cada** PR. `-m postgres` (docker 5433) verde
  al menos en PR0, PR1, PR4a/b y PR5.
- Diff sucio = defecto de base: se retarguetea o se rebasa hasta que sólo aparezca la unidad de
  trabajo actual.
- El tracker queda draft hasta que toda la cadena esté revisada e integrada; sólo el tracker va
  a `main`.
- Commits por **unidad de trabajo** con Conventional Commits, tests junto al comportamiento que
  verifican, sin atribución de IA.

---

## Componentes y flujo de datos (resumen del estado final)

```
cli.py (argparse + resolución config/banderas)   <- única superficie de usuario
   ├── comandos/procesar.py  -> LanzadorCorrida -> despacho_paralelo|tareas -> EscritorPostgres
   └── comandos/servir.py    -> rutas_corridas / ServicioCorridasReal -> embudo_corrida

pipeline/etapas.py::Etapa   (fuente de verdad de NOMBRES de etapa, 10 miembros)
   ├── dominio/errores.py::EtapaDocumento   (sin cambios de firma; `str |` preservado)
   ├── web/embudo_corrida.py::ORDEN_EMBUDO  (orden de PRESENTACIÓN, explícito)
   └── test de correspondencia `_ETAPA` en src/  (la deriva se detecta con prueba, no con tipo)

salida/destinos/postgres.py::_ESCRITORES_POR_TIPO   (whitelist == despacho, misma estructura)
salida/constructor_registro.py::_CONSTRUCTORES_POR_TIPO (registry; conserva ValueError)
pipeline/coordinador_episodios.py::CoordinadorEpisodios(tipos_requeridos=...)  (inyectado)
```

Puntos de integración que **no** se tocan (no-objetivos de la propuesta, acatados): lógica de
`despacho_paralelo.py`, panel web, `esqueleto.py`, la re-derivación independiente
`parseo/`↔`reconciliacion/`, `MetricasDespacho`, y todo lo que protege datos de pacientes.

## Supuestos explícitos (no verificados)

1. Los tiempos de `uv build` / `uv venv` / instalación `--no-deps` (~12-20 s en total) son
   estimación, no medición en esta máquina.
2. El costo de `CREATE DATABASE`/`DROP DATABASE` por módulo de caracterización (~1 s) es
   estimación.
3. El site-packages del venv efímero precede al heredado por `--system-site-packages` en
   `sys.path`: es el comportamiento documentado de `site`, pero el diseño **no confía** en él —
   por eso existe la guarda de honestidad del punto 1 de D2.
4. Las estimaciones de líneas por PR se derivan de conteos reales de archivos
   (`scripts/` 856, `tests/scripts/` 1.245) y de la forma del cambio, no de un diff ya hecho.
