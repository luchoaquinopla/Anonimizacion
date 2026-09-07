"""Estados de corrida y de documento: infraestructura de reanudación, no conectada aún.

`RepositorioCorridas` (`ingesta/repositorio_corridas.py`) persiste estas
enumeraciones y `dominio/corridas.py` valida sus transiciones, pero el camino
real de producción (`trabajadores/tareas.py::procesar_grupo` ->
`EjecutorPipeline.procesar_lote`) sólo escribe `EstadoDocumentoCorrida.INVENTARIADO`
al inventariar (`LanzadorCorrida.lanzar` -> `registrar_documentos`) y nunca
avanza el estado desde ahí: no hay llamador de producción de
`actualizar_documento` ni de `documentos_para_reanudar` hoy.

Por qué se conserva igual (`chore/resolver-codigo-desconectado`): es la
infraestructura que hace falta para reanudar una corrida cortada sin
reprocesar desde cero -- con ~400.000 documentos proyectados y corridas de
horas, no es opcional. `POST /corridas/{id}/reintentar` devuelve 501 a
propósito (`web/rutas_corridas.py`) porque esa reanudación no existe todavía.

Qué falta para conectarlo: que `procesar_grupo` persista el estado terminal
de cada documento (`APROBADO`, `CUARENTENA` o `ERROR_FINAL`) al terminar, y
que el relanzador de una corrida cortada use `documentos_para_reanudar` para
saltar los grupos ya resueltos. Eso es trabajo nuevo y su propio cambio, no
parte de esta limpieza.

Los estados intermedios de documento (`CLASIFICADO`, `EXTRAIDO_MINIMO`,
`ASOCIADO`, `EXTRAIDO_COMPLETO`, `RECONCILIADO`) modelaban una extracción por
etapas que sí se implementó (`configurar_extractor` en `trabajadores/tareas.py`)
pero se eliminó en este mismo cambio: la unidad de trabajo real es el GRUPO
completo procesado en una sola llamada síncrona, no un documento avanzando
etapa por etapa entre tareas Celery separadas -- ver
`openspec/changes/procesamiento-por-grupo/exploration.md`. Si la reanudación
por grupo se construye, decidir ahí si estos estados intermedios siguen
teniendo sentido o si conviene colapsarlos a una granularidad más gruesa.
"""

from __future__ import annotations

from enum import Enum


class EstadoCorrida(str, Enum):
    CREADA = "creada"
    INVENTARIANDO = "inventariando"
    PROCESANDO = "procesando"
    RECONCILIANDO = "reconciliando"
    PUBLICANDO = "publicando"
    COMPLETADA = "completada"
    COMPLETADA_CON_CUARENTENA = "completada_con_cuarentena"
    FALLIDA = "fallida"


class EstadoDocumentoCorrida(str, Enum):
    INVENTARIADO = "inventariado"
    CLASIFICADO = "clasificado"
    EXTRAIDO_MINIMO = "extraido_minimo"
    ASOCIADO = "asociado"
    EXTRAIDO_COMPLETO = "extraido_completo"
    RECONCILIADO = "reconciliado"
    APROBADO = "aprobado"
    CUARENTENA = "cuarentena"
    ERROR_RECUPERABLE = "error_recuperable"
    ERROR_FINAL = "error_final"
