# Diseño: puerto de ingesta

## Enfoque técnico

Un `Protocol` `FuenteDeArtefactos` en `ingesta/fuente.py` con `listar() -> Iterator[ArtefactoCrudo]` y `abrir(artefacto) -> BinaryIO`, simétrico a `DestinoEscritura`/`DestinoCuarentena` (`ejecutor.py` L83/L98). Un único adaptador `FuenteLocal` reemplaza a `FuenteArtefacto` e `InventariadorDocumentos`. El core deja de conocer `pathlib`: `ejecutor.py:181` pasa a `extraer_texto_de_flujo(fuente.abrir(artefacto))`.

## Decisiones de arquitectura

### Decisión 1: deduplicación delegada, no un `set` en memoria

El `set` de sha256 hex de hoy es la única estructura que crece de forma monótona con el corpus. Un `str` hex de 64 caracteres cuesta ~113 B más ~32 B de slot amortizado en el `set` (factor de carga 3/5).

| Elementos | `set` de hex (`str`) | `set` de digests (`bytes`, 32 B) |
|---|---|---|
| 100.000 | ~14 MB | ~10 MB |
| 500.000 | ~72 MB | ~48 MB |
| 1.000.000 | ~145 MB | ~97 MB |

Referencia dura: el ensayo de carga midió **301 MiB de pico para 10.000 documentos**. A 1.000.000 de archivos el `set` solo ya iguala la mitad de ese pico, y a ~5 TB de corpus el `set` es lo que **anula la pereza**: `listar()` rinde de a uno pero sigue siendo O(N) en memoria. Peor: el `set` muere con el proceso, y una corrida de 5 TB **va** a interrumpirse.

| Opción | Tradeoff | Decisión |
|---|---|---|
| `set` de digests binarios | Ahorra ~33%; sigue siendo O(N) y volátil | Rechazada: pospone el problema, no lo resuelve |
| SQLite local nuevo | Persistente y acotado; agrega un almacén más que mantener, respaldar y limpiar | Rechazada: duplica infraestructura existente |
| Delegar en `RepositorioCorridas` | Ya existe, ya persiste, ya deduplica | **Elegida** |

`RepositorioCorridas.registrar_documento` (`ingesta/repositorio_corridas.py:36`) ya devuelve `False` ante `huella_contenido` repetida dentro de la corrida, con `UniqueConstraint("corrida_id", "huella_contenido")` en `modelos_orm.py:209` que la hace segura ante concurrencia de workers. Además es lo que `tareas.py` ya lee vía `documentos_para_reanudar`: inventariar **es** registrar documentos de la corrida.

`FuenteLocal` no importa SQLAlchemy. Recibe un `RegistroDeHuellas` (`Protocol` con `es_nueva(sha256: str) -> bool`) con dos implementaciones: `HuellasEnMemoria` (default, tests y corridas chicas) y `HuellasDeCorrida` (envoltorio delgado sobre `RepositorioCorridas`, uso productivo). **Tradeoff**: un round-trip a DB por archivo durante el inventario. Aceptable porque el inventario ya está dominado por leer el archivo entero para hashearlo; un `INSERT` indexado es ruido frente a eso.

### Decisión 2: `abrir()` revalida la raíz y verifica la huella

| Aspecto | Decisión | Fundamento |
|---|---|---|
| Ciclo de vida | `abrir()` devuelve un `BinaryIO` fresco e independiente; **cierra el llamador** con `with` | Un objeto de archivo ya es context manager: se respeta la firma acordada sin envoltorios |
| Construcción del adaptador | La fábrica registrada por `configurar_ejecutor` (`tareas.py:41`) construye `FuenteLocal` una vez al arrancar el worker y la inyecta en `EjecutorPipeline(fuente=...)` | Ya es la raíz de composición del worker; no se agrega estado global nuevo |
| Resolución de `uri` | `abrir()` revalida la `uri` contra `raices_autorizadas` antes de abrir | La `uri` llega **desde la cola**. Hoy nadie la revalida del lado del worker: es un agujero real que este cambio cierra |
| Integridad | Verifica el sha256 sobre los bytes ya leídos | PyMuPDF necesita el buffer completo igual; el segundo pase de hash es despreciable frente al parseo |

El tope de tamaño es lo que **acota la memoria del worker**: sin él, `flujo.read()` es un vector de agotamiento de memoria.

### Decisión 3: sobretamaño a cuarentena sin filtrar el nombre de archivo

Se agrega `CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO`, `EtapaDocumento.INGESTA` y dos campos numéricos opcionales en `ErrorDocumento` (`tamano_bytes`, `tope_bytes`) — números, no mensajes crudos, coherente con "sin PII en cola, logs ni DLQ".

`id_documento` del artefacto rechazado = `sha256` de la **ruta**, no del contenido. En un corpus clínico el nombre de archivo puede contener el nombre del paciente, así que no se propaga. Tampoco se hashea el contenido: es exactamente la lectura de un archivo enorme que queremos evitar. **Tradeoff**: el operador debe re-derivar el hash de ruta localmente para ubicar el archivo; no hay identidad de contenido de algo que nos negamos a leer.

`FuenteLocal` declara su **propio** `Protocol` de sumidero de cuarentena (`registrar(error)`), sin importar el de `ejecutor.py`. `EscritorCuarentena` satisface ambos por tipado estructural; `ingesta` no debe depender de `pipeline`.

### Decisión 4: `extraer_texto` conserva su firma

| Opción | Tradeoff | Decisión |
|---|---|---|
| Cambiar a `Path \| bytes` | Obliga a `isinstance` dentro de la función central de extracción: la complejidad accidental que estamos sacando | Rechazada |
| Reemplazar la firma | Rompe 13 llamadas, entre ellas las tres compuertas de calibración (`tests/calibracion/`), arneses de regresión cuyo valor **es** su estabilidad | Rechazada |
| Variante nueva | Un punto de bifurcación explícito | **Elegida** |

Nace `extraer_texto_de_flujo(flujo: BinaryIO) -> TextoExtraido` con toda la lógica (`pymupdf.open(stream=..., filetype="pdf")`). `extraer_texto(ruta: Path)` queda como envoltorio de tres líneas, marcado en el docstring como conveniencia de CLI y tests: **el pipeline no lo usa**. Gotcha: con `stream=`, un buffer vacío levanta `pymupdf.EmptyFileError`; debe mapear a `PARSEO_INCOMPLETO` igual que hoy, porque el caso `corrupto` de `corpus_piloto` depende de ese código exacto.

### Decisión 5: `listar()` valida antes de ser generador

Un generador difiere su cuerpo hasta el primer `next()`, así que `pytest.raises(PermissionError)` alrededor de `fuente.listar()` **no dispararía**. `listar()` es una función normal que valida raíz y directorio y luego devuelve un generador interno. La asimetría es deliberada: raíz no autorizada es fallo duro (`PermissionError`); sobretamaño es cuarentena por artefacto.

## Flujo

```mermaid
sequenceDiagram
    participant D as Despachador
    participant F as FuenteLocal
    participant H as RegistroDeHuellas
    participant Q as Cuarentena
    participant C as Cola Celery
    participant W as Worker (tareas.py)
    participant E as EjecutorPipeline
    participant X as extraer_texto_de_flujo

    D->>F: listar()
    F->>F: valida raiz autorizada (PermissionError si no)
    loop por archivo
        F->>F: stat().st_size
        alt supera el tope
            F->>Q: registrar(ARTEFACTO_SOBRETAMANO, tamano, tope)
        else
            F->>F: sha256 por bloques de 1 MiB
            F->>H: es_nueva(sha256)
            alt duplicado
                H-->>F: False (se omite)
            else
                F-->>D: yield ArtefactoCrudo
                D->>C: procesar_documento(id, uri, sha256)
            end
        end
    end
    C->>W: {id_documento, uri, sha256}
    W->>E: procesar_lote([ItemLote])
    E->>F: abrir(artefacto)
    F->>F: revalida uri contra raices autorizadas
    F-->>E: BinaryIO
    E->>X: extraer_texto_de_flujo(flujo)
    X->>X: bytes = flujo.read(); verifica sha256
    X-->>E: TextoExtraido
```

La cola sigue transportando exactamente `{id_documento, uri, sha256}`: ningún byte ni handle la cruza.

## Cambios por archivo

| Archivo | Acción | Descripción |
|---|---|---|
| `src/anonimizacion/ingesta/fuente.py` | Modificar | `FuenteDeArtefactos`, `RegistroDeHuellas`, `SumideroCuarentena`, `FuenteLocal`, `HuellasEnMemoria`; se eliminan `FuenteArtefacto` e `InventariadorDocumentos` |
| `src/anonimizacion/ingesta/huellas_corrida.py` | Crear | `HuellasDeCorrida` sobre `RepositorioCorridas` |
| `src/anonimizacion/dominio/errores.py` | Modificar | `ARTEFACTO_SOBRETAMANO`, `EtapaDocumento.INGESTA`, `tamano_bytes`/`tope_bytes` |
| `src/anonimizacion/extraccion/texto_pymupdf.py` | Modificar | `extraer_texto_de_flujo`; `extraer_texto` pasa a envoltorio |
| `src/anonimizacion/pipeline/ejecutor.py` | Modificar | Parámetro `fuente`; se van `Path` y `extraer_texto` de los imports |
| `src/anonimizacion/ingesta/artefacto.py` | Verificar | Debe seguir sin contenido (test de payload) |
| `scripts/procesar_carpeta.py` | Modificar | Materializa el iterador y construye `FuenteLocal` |
| `tests/ingesta/test_fuente.py` | Reescribir | Contra el adaptador unificado |
| `tests/fixtures/corpus_piloto.py` | Modificar | `tuple(fuente.listar())` + sumidero de cuarentena |

## Migración de consumidores

**`scripts/procesar_carpeta.py:87`** — `artefactos = list(fuente.listar())`, se conserva el guardia `if not artefactos`. Honestidad necesaria: `procesar_lote` recibe una `Sequence` y la coordinación de episodios opera sobre el lote entero, así que materializar acá es **inherente**, no una falla de migración. La pereza rinde en el camino de despacho a cola (una tarea por artefacto emitido), no en `procesar_lote`.

**`tests/ingesta/test_fuente.py`** — nueve tests migran. Cambia solo uno de forma semántica: el de sobretamaño pasa de `pytest.raises(ValueError)` a afirmar una entrada de cuarentena con `tamano_bytes` y `tope_bytes` reales. Los de raíz no autorizada y symlink que escapa se conservan sin cambio de comportamiento. Se agrega el test de pereza (primer `ArtefactoCrudo` sin hashear el resto) y el de doble puerto (adaptador en memoria, sin filesystem).

**`tests/fixtures/corpus_piloto.py:143`** — `InventariadorDocumentos((directorio,), 10 MiB).inventariar(entrada)` pasa a `FuenteLocal(raices=(directorio,), directorio=entrada, tope_bytes=10 MiB, huellas=HuellasEnMemoria(), cuarentena=_CuarentenaMemoria())`. `documentos_inventariados` conserva su semántica (únicos tras dedup), así que `ORACULO_CARGA_1000` no debería moverse: ningún caso del plan supera 10 MiB. **Igual hay que correr de nuevo los ensayos de 1.000 y 10.000** — el oráculo es de igualdad estricta y el pico de memoria y el throughput son parte del contrato de `tests/carga/ejecutar_corpus.py`. Con `HuellasEnMemoria` el pico no debería subir; si baja, se actualiza `evaluar_preflight` (`memoria_estimada`, hoy 145.432.576 B por cada 1.000).

## Estrategia de pruebas

| Capa | Qué | Cómo |
|---|---|---|
| Unidad | Pereza, dedup, sobretamaño, raíz no autorizada, symlink | `tmp_path` + adaptador en memoria |
| Unidad | `extraer_texto_de_flujo` con PDF corrupto, vacío y multipágina | PDFs sintéticos en `BytesIO` |
| Unidad | `abrir()` rechaza una `uri` fuera de raíz y un sha256 que no coincide | Simula una cola envenenada |
| Contrato | `FuenteLocal` satisface el `Protocol` | `typing.assert_type` |
| Integración | Pipeline completo con fuente en memoria, sin filesystem | `tests/pipeline/` |
| Integración | Payload de cola == `{id_documento, uri, sha256}` | Serialización en `tests/trabajadores/` |
| Carga | 1.000 y 10.000 PDFs | Corrida fresca contra el oráculo |

## Despliegue

Sin migración de datos. `RepositorioCorridas` y su `UniqueConstraint` ya existen. Contrato interno sin consumidores productivos: `git revert` del rango alcanza. El rewiring de `ejecutor.py` puede revertirse solo, dejando el puerto sin consumidores.

## Preguntas abiertas

- [ ] Tope por default: 50 MiB provisional. Requiere confirmación del instituto contra la distribución real de tamaños.
- [ ] `HuellasDeCorrida` necesita un `corrida_id`; quién lo asigna en el camino de despacho queda para `sdd-tasks`.
- [ ] Verificar la huella en `abrir()` obliga a leer el flujo entero antes de entregarlo a PyMuPDF. Confirmar con el ensayo de 10.000 que no mueve el pico de memoria.
