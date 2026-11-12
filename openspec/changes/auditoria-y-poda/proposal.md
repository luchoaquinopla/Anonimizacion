# Propuesta: auditoría y poda

Cerrar los defectos latentes que la auditoría del 2026-09-16 confirmó en `src/anonimizacion`,
retirar la capacidad declarada que nunca se operó, y podar la prosa del código a un tamaño
que se pueda mantener sincronizado. Seis entregas encadenadas, cada una verificable por sí
sola.

## Por qué ahora

La auditoría (Engram `auditoria/consolidado-2026-09`, obs #1338) dio un veredicto tranquilizador
sobre la estructura y uno incómodo sobre los detalles:

| Dimensión | Resultado |
|---|---|
| Arquitectura hexagonal | Cero violaciones, cero ciclos de import |
| Código muerto | 1 sola línea real (`observabilidad/bitacora_segura.py:56`) |
| Duplicación nociva | Poca; la que hay es deliberada (ver No-objetivos) |
| Defectos latentes | 4 confirmados, **todos de falla silenciosa** |
| Prosa | 4.618 líneas de docstring + 1.402 de comentario sobre ~9.500 de código ejecutable |

Tres razones para hacerlo ahora y no después:

1. **El próximo tipo de documento es el detonante.** Tres defectos (Entrega 1) no se
   manifiestan hoy porque hay exactamente 3 tipos de documento. Al agregar
   cinecoronariografía los tres explotan, y ninguno levanta una excepción: uno escribe datos
   del tipo nuevo en las tablas del eco, otro manda a cuarentena episodios completos. Se
   arreglan barato ahora y caro después, en medio de un parser nuevo.
2. **Hay un defecto de despliegue vivo.** `anonimizacion procesar` y `anonimizacion servir`
   funcionan desde checkout y fallan instalados por wheel (Entrega 4). Es exactamente el
   comando que `deploy/operacion-institucional.md` le entrega a IT del instituto.
3. **La prosa se está desincronizando a la vista.** `cli.py:20-34` justifica un diseño citando
   un PR #40 "abierto" que está mergeado (847e711); `docs/pipeline.md:194` cita un módulo que
   no existe. Con 6.020 líneas de prosa nadie las relee; con ~1.500 sí.

## Alcance: siete entregas

> **Principio rector del cambio: mejorar, nunca retroceder.** Cuatro de las siete entregas tocan
> lógica de producción (E1, E2, E4, E5) y dos borran código. Por eso la red de seguridad se teje
> ANTES de tocar nada: la Entrega 0 no cambia una sola línea de `src/`.

### Entrega 0 — Red de seguridad: caracterizar el comportamiento actual

No modifica producción. Fija por escrito **lo que el sistema hace hoy**, para que cualquier
cambio posterior que lo altere sin querer falle de inmediato.

Por qué va primero y no después: un test de caracterización escrito *después* de refactorizar
sólo consagra el comportamiento ya modificado. Documenta el resultado, no el punto de partida.

| Qué se caracteriza | Por qué | Protege a |
|---|---|---|
| **Punta a punta del pipeline** sobre corpus sintético: los 3 tipos, un episodio completo, uno incompleto, uno ambiguo y uno en cuarentena. Se fijan las filas resultantes en Postgres y el registro de salida | Es el único oráculo que cubre las 9 etapas juntas. Si algo se rompe en el medio, acá se ve | E1, E2, E4, E5 |
| **Contrato del CLI**: para cada subcomando, el conjunto de banderas aceptadas, los valores por defecto efectivos y los códigos de salida | E4 elimina el doble parsing de argparse. Sin esta foto previa no hay forma de demostrar que el comportamiento se preservó | E4 |
| **Códigos de cuarentena observables**: qué entrada produce qué `CodigoErrorDocumento`, con su etapa | E2 y E5 tocan el camino de errores y métricas. Un código que cambia de etapa o desaparece rompe el panel del médico en silencio | E2, E5 |
| **Vista del embudo**: dado un conjunto conocido de documentos, el desglose exacto que ve el codirector médico | E2 redefine `ETAPAS_EMBUDO`. Este test es lo que impide que el panel cambie sin que nadie lo decida | E2 |
| **Salida del reporte de corrida** que hoy lee `MetricasDespacho` | E5 borra el OTRO sistema de métricas. Esto demuestra que se borró el correcto | E5 |

**Regla de honestidad**: estos tests deben poder fallar. Cada uno se valida rompiendo a propósito
lo que dice proteger y comprobando que se pone en rojo. Un test de caracterización que pasa con
el sistema roto es peor que no tenerlo: da permiso para seguir.

**Restricción**: fixtures sintéticas, nunca PDFs reales con PII (AGENTS.md). Ninguna fixture
escribe sobre la base de desarrollo compartida del puerto 5433: cada una crea y destruye la suya.

### Entrega 1 — Trampas latentes de extensión

Tres puntos donde agregar un 4to tipo de documento falla en silencio.

| Archivo | Defecto | Arreglo |
|---|---|---|
| `salida/destinos/postgres.py:386-391` | `if/elif/else -> _escribir_eco`. La whitelist (`:320`) y el despacho (`:386`) son estructuras separadas: agregar un tipo a la whitelist y olvidar el despacho escribe los datos del tipo nuevo en las tablas del eco, sin error | Dict `{tipo: método}` — whitelist y despacho pasan a ser la MISMA estructura. `KeyError` ruidoso en vez de `else` mudo |
| `pipeline/coordinador_episodios.py:128` | `set(tipos) != _TIPOS_REQUERIDOS`, igualdad exacta contra un frozenset de 3. Un episodio COMPLETO de 4 estudios cae en cuarentena por `ESTUDIOS_FALTANTES` | Diferencia de conjuntos (`_TIPOS_REQUERIDOS - set(tipos)`) + inyectar el conjunto requerido en `CoordinadorEpisodios.__init__` en vez de constante de módulo |
| `salida/constructor_registro.py:231-246` | Cadena `if/elif/else raise ValueError` por tipo | Registry dict, el MISMO idioma que ya usan `parseo/registro.py:20-24` y `reconciliacion/registro.py:13-17` |

**Requisito TDD no negociable**: cada arreglo necesita un test que falle ANTES. El test debe
simular la llegada de un 4to tipo (miembro de prueba en el enum, o parametrización). **Un test
que use sólo los 3 tipos de hoy NO PUEDE FALLAR y no sirve de nada** — es el modo de fracaso
más probable de esta entrega.

### Entrega 2 — Vocabulario único de etapas

Hoy conviven tres vocabularios divergentes:

- `dominio/errores.py:16-36` `EtapaDocumento` — tiene `DESPACHO`, no tiene `COORDINACION`
- `pipeline/etapas.py:23-37` `Etapa` — tiene `COORDINACION`, no tiene `DESPACHO`
- `web/embudo_corrida.py:59-68` `ETAPAS_EMBUDO` — 8 strings planos, sin `deteccion` ni `deteccion_pii`

`ErrorDocumento.etapa` acepta `str | EtapaDocumento` (`errores.py:243`), así que **el tipo no
atrapa la deriva**: `ejecutor.py:508` mete `Etapa.COORDINACION.value` en un campo cuyo enum no
tiene ese miembro. El bug ya ocurrió — quedó documentado en `embudo_corrida.py:55-58`.

#### Corrección al análisis original (verificada contra el código)

La primera versión de esta propuesta pedía **quitar el `str |` de la unión**. Eso está **MAL** y
no se hace. `pipeline/etapas.py:1-16` documenta que los `str` planos son deliberados:

> son `str` planos **por diseño**, para no acoplar `dominio/errores.py` a esta capa más nueva

Y se usan sistemáticamente: `parseo/registro.py:18`, `parseo/ecg_mortara.py:87`,
`parseo/laboratorio_general.py:115`, `parseo/eco_doppler.py:69`,
`extraccion/texto_pymupdf.py:57`, todos con `_ETAPA = "parseo"` / `"extraccion"`. Endurecer el
tipo **acoplaría el dominio y los parsers a la capa de pipeline**, que es justamente lo que
alguien evitó a propósito. Peor: convertiría un valor hoy tolerado en una excepción **dentro del
camino de manejo de errores** — el sistema reventaría justo cuando algo ya había fallado.

#### Qué se hace en su lugar

Mantener el desacople y **detectar la deriva con una prueba, no con el tipo**:

1. Un único enum como fuente de verdad de los NOMBRES de etapa (no de los tipos de los campos).
2. Un test que afirme que **todo `_ETAPA` declarado en `src/` es miembro de ese enum**, y que
   todo miembro del enum de errores tiene correspondencia. Falla si alguien agrega una etapa en
   un solo lado.
3. Derivar `ETAPAS_EMBUDO` del enum, con el orden de presentación **decidido explícitamente**
   (no heredado por accidente del orden de declaración: le cambia la vista al codirector médico).

Toca ~5 archivos y los tests de `embudo_corrida`. **No** toca las firmas de `dominio/errores.py`.

### Entrega 3 — Restaurar poder de detección en los tests

No es limpieza: es recuperar capacidad de atrapar bugs que hoy se perdió.

- **Quinto test espejo.** `tests/pipeline/test_equivalencia_agrupacion.py:51-104` (104 líneas,
  4 tests) compara `_episodios_del_coordinador(x)` contra `vincular_episodios(x)`, pero
  `coordinador_episodios.py:86-103` `_agrupar_por_ancla` DELEGA en `vincular_episodios`. Es
  `f(x) == g(x)` donde `f` llama a `g`: no puede fallar jamás. Fue válido cuando había dos
  implementaciones; el refactor a delegación lo dejó tautológico. **Decisión a tomar en
  `sdd-design`**: reemplazarlo por un test con oráculo independiente (fechas y agrupaciones
  esperadas escritas a mano) o eliminarlo documentando por qué. En cualquiera de los dos casos
  hay que corregir el docstring de producción `coordinador_episodios.py:9-13`, que sigue
  afirmando que ese test "fija esa equivalencia como contrato".
- **Gap de oráculo.** `tests/reconciliacion/` tiene 31 tests sin `assert` y sin `pytest.raises`
  (p. ej. `test_ecg_mortara.py:57` y `:77`) que llaman `reconciliar(...)` y descartan el
  resultado. "No explotó" es la única verificación, pero el retorno es el conjunto de campos NO
  extraídos: una regresión por la vía de degradación pasa en silencio con el test llamándose
  `test_aprueba_...`. Agregar aserción real sobre el valor de retorno.
- **Gap de cobertura.** No existe test que garantice que todo `CodigoErrorDocumento` que llegue
  a cuarentena tenga entrada en `web/codigos_cuarentena.py::EXPLICACION_POR_CODIGO`. Si alguien
  agrega un código y olvida la tabla, el panel le muestra el código crudo al médico. Agregar
  test de exhaustividad.

### Entrega 4 — CLI: eliminar el reenvío a `scripts/`

Defecto real de despliegue, verificado contra el código:

- `cli.py:54` `_RAIZ_REPO = Path(__file__).resolve().parents[2]`
- `cli.py:59` carga `scripts/<archivo>` por ruta con `spec_from_file_location`, monkeypatchea
  `sys.argv` y llama `modulo.main()`, que RE-PARSEA argparse
- `pyproject.toml:35` `packages = ["src/anonimizacion"]` — **`scripts/` no se empaqueta**
- `pyproject.toml:32` declara el entry point `anonimizacion = "anonimizacion.cli:main"`

Conclusión: funciona desde checkout, falla instalado por wheel. La justificación escrita en
`cli.py:20-34` ("hay un PR #40 abierto") caducó: el PR #40 está mergeado.

Mover la lógica de `scripts/procesar_carpeta.py` y `scripts/servir_panel.py` a
`src/anonimizacion/`, eliminar el doble parsing, y eliminar el triplicado de `_DB_URL_DEFAULT`
(`configuracion.py:52`, `procesar_carpeta.py:80`, `servir_panel.py:107`). ~2.101 líneas afectadas
(856 de scripts + 1.245 de sus tests).

**Exigencia**: un test que verifique el entry point en una instalación por wheel (build + install
en venv efímero + invocar `anonimizacion --help` y el subcomando). Sin ese test el bug vuelve, y
vuelve invisible: toda la suite actual corre desde checkout, que es justamente el escenario donde
el defecto no se manifiesta.

### Entrega 5 — Retirar Celery/Redis y las métricas de sólo escritura

**Celery** (`trabajadores/app.py:23`, `tareas.py:150`) es una cáscara: `@app.task` decora
`procesar_grupo`, pero todo llamador de producción la invoca en directo
(`scripts/procesar_carpeta.py:171` lo dice textual); `.delay()` sólo existe en
`tests/trabajadores/test_tareas.py:143`; no hay servicio redis en docker-compose; el paralelismo
real lo hace `ProcessPoolExecutor` en `despacho_paralelo.py`. Lo más grave:
`deploy/operacion-institucional.md:48-51` **instruye a IT del instituto a configurar 4 variables
`CELERY_*` de un camino que no se ejecuta**. Corregir ese documento es parte obligatoria de la
entrega, no un extra.

**Métricas de sólo escritura** (`observabilidad/metricas.py:41-103`): se escriben 3 contadores
desde `ejecutor.py:334,610,647`, pero `.snapshot()` y `.resumen_operacional()` nunca se llaman
fuera de tests, y `tareas.py:135` crea una `MetricasEnMemoria()` nueva por grupo — estructuralmente
ilegible. El panel deriva el avance de la base (`web/embudo_corrida.py`), no de acá.

> **Cuidado**: existe un segundo sistema, `despacho_paralelo.py:330` `MetricasDespacho`, que SÍ
> se lee (`scripts/procesar_carpeta.py:219-223`). **Ese no se toca.**

**Código muerto**: `observabilidad/bitacora_segura.py:56` `CODIGOS_SEGUROS` (1 línea, sin referencias).

#### Por qué retirar capacidad declarada es mejor que mantenerla

Esta entrega borra una capacidad anunciada, así que el argumento tiene que estar escrito:

- La capacidad **no existe**: nunca se ejecutó en producción, no tiene infraestructura
  (sin redis en compose) y su único uso es un test que prueba el decorador, no el sistema.
- **Miente hacia afuera y hace daño**: le pide a IT del instituto configurar y sostener cuatro
  variables de entorno de un camino muerto. Eso consume tiempo de terceros y crea la falsa
  creencia de que hay workers distribuidos corriendo.
- **Tiene costo de mantenimiento silencioso**: obliga a que cada cambio en `procesar_grupo`
  preserve una firma compatible con Celery que nadie ejercita.
- **El camino de vuelta es barato y está documentado**: el propio openspec archivado
  `paralelismo-de-procesamiento/proposal.md:89` dice que migrar a `.delay()` sería una línea.
  Si mañana se quieren workers distribuidos, el trabajo real es la infraestructura (redis,
  supervisión, reintentos), no el decorador — y esa infraestructura hay que construirla igual,
  exista o no el decorador hoy.

### Entrega 6 — Poda de comentarios

Decisión del usuario, y la segunda razón por la que existe este cambio. Regla acordada:

| Elemento | Regla |
|---|---|
| Docstrings | **Máximo 2 líneas.** Qué hace la función y qué devuelve. Texto corto, preciso, representativo |
| El *por qué* narrativo | Historia, referencias a PRs, decisiones: **migra a Obsidian/openspec** y desaparece del código |
| Invariantes medidos y trampas conocidas | **Excepción innegociable.** Sobreviven comprimidos a UNA línea con puntero: `# 875 MB RSS por motor -- ver D-0XX en Obsidian` |

Ejemplos que **no se pueden perder** bajo ninguna circunstancia:

- La medición de 875 MB de RSS por `MotorPii` en `despacho_paralelo.py` (medida con ctypes; es
  lo que fija el grado de concurrencia).
- El motivo de cada `noqa: C901` en `pyproject.toml:56-72` (no se tocan sin corpus de PDFs
  reales; ya se descalibró dos veces).
- Los carteles anti-espejo, p. ej. `tests/salida/test_esquema_arrow_de_exportacion.py:1-13`.

**Orden obligatorio: primero MIGRAR a Obsidian, después podar.** Nada se borra sin haber
aterrizado antes. Si se poda primero, el conocimiento se pierde y ningún test avisa.

De paso, corregir la prosa ya desincronizada: `cli.py:20-34` (PR #40 citado como abierto, está
mergeado) y `docs/pipeline.md:194` (cita `extraction/pymupdf_text.py`, inexistente; el real es
`extraccion/texto_pymupdf.py`).

Volumen: ~6.020 líneas de prosa hoy, objetivo del orden de 1.500.

## Fuera de alcance

### Pendientes anotados (no se resuelven acá)

- **Doble pasada de spaCy.** `ejecutor.py:440` llama `self._clasificar_pii(...)` y descarta el
  `ResultadoPolitica`; `clasificar()` corre `_detecciones_texto_libre` (NER) y después
  `redaccion.py:133` `redactar_por_motor` llama `motor.detectar(texto)` otra vez sobre el mismo
  texto. Es un problema de rendimiento a 100k **sin medir en segundos todavía**. Queda anotado
  con su evidencia: meterlo en este cambio sin número sería adivinar cuánto se gana y cuánto se
  arriesga.
- **Archivar `openspec/changes/correccion-orientacion-senal-ecg/`**, cuyo PR #52 ya está mergeado
  a main (6e22d9b). Higiene pendiente, ajena a este cambio.

### Oportunistas (no justifican entrega propia)

Pueden entrar donde caigan naturalmente dentro de otra entrega, nunca como motivo de una:
`_primer_segmento` copiada 6 veces, tokens CSS duplicados entre `plantilla_panel.py` y
`plantilla_reporte.py`, heurística de sub-encabezado duplicada.

### No-objetivos (declarados para que nadie los "optimice" después)

| No tocar | Por qué |
|---|---|
| Re-derivación independiente `parseo/` ↔ `reconciliacion/` | Es **verificación cruzada deliberada**. Fusionarlas haría que un bug en el código compartido hiciera coincidir al parser con su propio verificador: el verificador dejaría de verificar |
| Panel web | Tiene usuario real nombrado: el codirector médico (`openspec/changes/archive/panel-de-operacion/proposal.md:5-6`) |
| `esqueleto.py` | Existe porque AGENTS.md prohíbe PDFs reales; los parsers ya se descalibraron dos veces |
| `despacho_paralelo.py` | Sólo comentarios (Entrega 6). La lógica de concurrencia no se toca |
| `MetricasDespacho` (`despacho_paralelo.py:330`) | Sí se lee. No confundir con `observabilidad/metricas.py` |
| Todo lo que protege datos de pacientes | PII, pseudonimización, cuarentena, auditoría: **no se recorta nada** |

## Orden de la cadena

Estrategia: `feature-branch-chain`. Rama integradora `feat/auditoria-y-poda` desde
`origin/main` @ 6e22d9b. PR tracker en draft/no-merge; PR #1 apunta a la integradora, cada PR
siguiente apunta al anterior. Sólo la integradora va a main.

```
main @6e22d9b
  └── feat/auditoria-y-poda (tracker, draft)
        └── PR0  Entrega 0 — red de seguridad (NO toca src/)
              └── PR1  Entrega 1 — trampas latentes de extensión
                    └── PR2  Entrega 2 — vocabulario único de etapas
                          └── PR3  Entrega 3 — poder de detección en tests
                                └── PR4  Entrega 4 — CLI sin reenvío a scripts/
                                      └── PR5  Entrega 5 — retiro de Celery y métricas muertas
                                            └── PR6  Entrega 6 — poda de comentarios
```

Justificación del orden:

0. **0 antes que todo, sin excepción**: caracteriza el comportamiento actual mientras el
   comportamiento actual todavía existe. Es la única entrega que no puede reordenarse: después de
   E1 el sistema ya cambió, y la foto del "antes" dejó de ser posible.
1. **1 después de la red**: son los arreglos más baratos y los de mayor riesgo latente; si la
   cadena se corta por cualquier motivo, esto ya está en la integradora.
2. **2 antes de 3**: el test de exhaustividad de códigos de cuarentena (Entrega 3) se escribe
   sobre el vocabulario ya unificado; al revés habría que reescribirlo.
3. **3 antes de 4 y 5**: las entregas que borran código (4 y 5) se apoyan en una suite que
   realmente detecta regresiones. Borrar 2.101 + N líneas con 31 tests sin oráculo es apostar.
4. **4 antes de 5**: la Entrega 5 toca `scripts/procesar_carpeta.py`; después de la 4 ese archivo
   ya vive en `src/`, así que se edita una sola vez en su ubicación final.
5. **6 al final, siempre**: la poda de prosa toca casi todos los archivos. Si va antes, cada PR
   posterior arrastra conflictos de merge en cada archivo que edite.

## Riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| **Entrega 6 borra un invariante medido y nadie se entera** | Alta | Alto — es conocimiento que costó mediciones y dos descalibraciones recuperar; ningún test lo protege | Orden obligatorio migrar→podar; lista explícita de invariantes protegidos en `sdd-spec`; la migración a Obsidian es criterio de aceptación de la entrega, no un paso suelto; revisión humana del diff de 6 por separado |
| Los tests de la Entrega 1 usan sólo los 3 tipos actuales y no pueden fallar | Alta | Alto — el arreglo se da por bueno sin verificar nada | Exigir demostración de rojo→verde con un 4to tipo simulado antes de aceptar cada arreglo |
| La Entrega 4 rompe el comando que usa IT del instituto | Media | Alto | Test de instalación por wheel dentro de la misma entrega; `deploy/operacion-institucional.md` se actualiza en el mismo PR |
| Retirar Celery cierra la puerta a workers distribuidos | Baja | Bajo | Documentado: el retorno es `.delay()` (una línea, per `paralelismo-de-procesamiento/proposal.md:89`); el costo real siempre fue la infraestructura |
| La Entrega 2 cambia el orden del embudo y el panel del médico queda raro | Media | Medio | El orden del embudo se decide explícitamente en `sdd-design`, no se deriva por accidente del orden de declaración del enum; tests de `embudo_corrida` actualizados en la misma entrega |
| La cadena de 6 PRs se estanca a mitad | Media | Medio | Cada entrega es independientemente valiosa y mergeable a la integradora; el orden está pensado para que cortar después de cualquier PR deje el repo coherente |
| Conflictos de merge por la extensión de la Entrega 6 | Media | Bajo | Va última, sobre todo lo demás ya integrado |

## Criterios de éxito

Por entrega, verificables:

- [ ] **E0** — `git diff` contra `main` no toca ningún archivo de `src/`. Existen tests de
      caracterización para las cinco áreas de la tabla. **Cada uno fue validado rompiendo a
      propósito lo que protege y quedó en rojo** — con la evidencia del rojo registrada en el PR.
      Ninguna fixture escribe sobre la base compartida del puerto 5433.
- [ ] **E1** — Existe un test por cada uno de los 3 defectos que falla en el commit anterior al
      arreglo y pasa después, y cada uno ejercita un 4to tipo de documento. `postgres.py` despacha
      por dict (whitelist y despacho son la misma estructura). `coordinador_episodios` recibe el
      conjunto requerido por `__init__`. `constructor_registro` usa registry.
- [ ] **E2** — Existe un único enum como fuente de verdad de los nombres de etapa, y un test que
      falla si un `_ETAPA` de `src/` no es miembro de él. **`ErrorDocumento.etapa` sigue aceptando
      `str`**: el desacople dominio↔pipeline se preserva a propósito.
      `ETAPAS_EMBUDO` se deriva del enum. `ruff` limpio y la suite verde. (El proyecto **no
      tiene** type checker: las dependencias de desarrollo son `pytest`, `pytest-cov` y `ruff`.
      Incorporar `mypy` sería un cambio aparte, con su propia discusión.)
- [ ] **E3** — Los tests de `tests/reconciliacion/` afirman **sobre el valor de retorno** de
      `reconciliar(...)` — el conjunto de campos no extraídos. Un `assert resultado is not None`
      no cumple este criterio: sería satisfacer la letra sin recuperar poder de detección. El test
      tautológico de equivalencia está reemplazado por uno con oráculo independiente o eliminado
      con justificación escrita, y el docstring de `coordinador_episodios.py:9-13` dice la verdad.
      Existe test de exhaustividad `CodigoErrorDocumento` → `EXPLICACION_POR_CODIGO` que falla si
      se agrega un código sin entrada.
- [ ] **E4** — `scripts/procesar_carpeta.py` y `scripts/servir_panel.py` no existen o no se cargan
      por ruta. Un test construye el wheel, lo instala en venv efímero y ejecuta
      `anonimizacion --help` y al menos un subcomando con éxito. `_DB_URL_DEFAULT` existe en un
      solo lugar.
- [ ] **E5** — Sin importaciones de `celery` en `src/`. `observabilidad/metricas.py` y
      `bitacora_segura.py:56 CODIGOS_SEGUROS` retirados. `deploy/operacion-institucional.md` ya no
      menciona variables `CELERY_*`. `MetricasDespacho` intacta y su lectura en el reporte de
      corrida sigue funcionando.
- [ ] **E6** — Ningún docstring supera 2 líneas salvo excepción justificada. **Cada invariante de
      la lista protegida está presente en Obsidian y referenciado desde una línea en el código**
      — este es el criterio que decide la entrega. `cli.py` y `docs/pipeline.md:194` sin prosa
      falsa. Suite verde sin cambios de comportamiento.

      > El conteo de líneas de prosa (~6.020 hoy, del orden de 1.500 esperadas) es **informativo,
      > no una compuerta**. Si la poda termina en 1.800 con los invariantes intactos, la entrega
      > está bien; si llega a 1.400 borrando un cartel anti-espejo, está mal. Convertir el número
      > en objetivo invita a sacrificar exactamente lo que esta entrega tiene que proteger.

Transversal:

- [ ] `uv run pytest -q -m "not postgres"` verde en cada PR de la cadena.
- [ ] Las pruebas de Postgres (`-m postgres`, docker puerto 5433) verdes al menos en E1, E4 y E5.
- [ ] Ningún PR de la cadena supera 400 líneas cambiadas sin `size:exception` registrado.
