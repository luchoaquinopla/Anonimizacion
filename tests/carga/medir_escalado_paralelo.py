"""Mide el escalado de CPU de `despacho_paralelo` con N=1,2,4 procesos.

**Qué mide, honestamente**: SOLO el tiempo de `EjecutorPipeline.procesar_lote`
por grupo, con los MISMOS dobles que ya usa `tests/fixtures/corpus_piloto.py`
(`_MotorPiiOffline`, `_DestinoMemoria`) -- el motor de PII real (spaCy) y la
escritura real a Postgres quedan afuera. Con dobles no hay espera de red que
solapar con concurrencia (la mitad ~55% del presupuesto real, según
`proposal.md`), así que la mejora que reporta este script es SOLO la de CPU
-- no representa el 82-88% de reducción total que motiva este cambio. Ver
`proposal.md`, sección "NO se puede verificar hoy", para esa distinción ya
documentada.

No forma parte de la suite de `pytest` (sin asserts de oráculo, es un banco
de medición, no un test de corrección) -- mismo precedente que
`tests/carga/ejecutar_corpus.py`/`ejecutar_corpus_10000.py`. Se ejecuta
directo:

    python tests/carga/medir_escalado_paralelo.py [--pacientes N] [--procesos 1,2,4]

Corre como `__main__` a propósito, no vía `importlib` dinámico: el
`initializer`/la función de trabajo de este módulo tienen que ser resolubles
por un hijo `spawn` (ver el docstring de
`anonimizacion.trabajadores.despacho_paralelo` para la verificación empírica
de por qué un módulo cargado por ruta sintética no lo es).

**Resultados de referencia** (sesión de implementación de este tramo, máquina
de 6 núcleos físicos / 12 lógicos, `--pacientes 320` = 960 documentos):

```
  procesos |   segundos |  speedup
         1 |     16.498 |    1.00x
         2 |     11.114 |    1.48x
         4 |      7.417 |    2.22x
```

Sub-lineal a propósito, no un defecto de la medición: con dobles el trabajo
por documento es casi nulo (`_MotorPiiOffline.detectar` retorna `()` sin
tocar spaCy), así que el costo FIJO de levantar cada proceso hijo
(`ProcessPoolExecutor` + reimportar `anonimizacion` + `_inicializar_trabajador_offline`)
pesa proporcionalmente más cuanto más chico es el trabajo real que ese hijo
hace. Con el motor real (spaCy, ~61,8 ms de CPU/documento medidos en el
proposal, `openspec/changes/paralelismo-de-procesamiento/proposal.md`), el
trabajo por documento es varios órdenes de magnitud mayor que el costo de
arrancar el proceso, así que el escalado real debería acercarse más a lineal
que estos números -- pero eso NO está medido acá, solo razonado.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_RAIZ_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RAIZ_REPO / "src"))
sys.path.insert(0, str(_RAIZ_REPO))

from anonimizacion.ingesta.fuente import FuenteLocal, HuellasEnMemoria  # noqa: E402
from anonimizacion.trabajadores import despacho_paralelo, tareas  # noqa: E402
from anonimizacion.trabajadores.despacho_paralelo import Grupo  # noqa: E402

from tests.fixtures.corpus_piloto import (  # noqa: E402
    _CuarentenaMemoria,
    _DestinoMemoria,
    _MotorPiiOffline,
    _resolver_claves,
)
from tests.fixtures.pdf_sintetico import generar_corpus_clinico  # noqa: E402

PEPPER_MEDICION = b"pepper-medicion-escalado-nunca-produccion"


def _generar_corpus_agrupado(directorio: Path, *, pacientes: int, semilla_base: int) -> None:
    """Un `paciente-NNNN/` por episodio -- exactamente la forma que
    `FuenteLocal.listar_grupos()` espera (subdirectorio inmediato = grupo,
    ver su docstring)."""
    for indice in range(pacientes):
        carpeta = directorio / f"paciente-{indice:04d}"
        generar_corpus_clinico(carpeta, semilla=semilla_base + indice)


def _referencias_de_grupo(grupo_artefactos: tuple, *, directorio_raiz: Path) -> Grupo:
    """`id_documento` sigue la convención `{clave_grupo}__{tipo}` que ya usa
    `tests/fixtures/corpus_piloto.py::_resolver_claves` -- reusar esa función
    tal cual, sin duplicarla, en vez de inventar una resolución de identidad
    nueva solo para este script. `clave_grupo` es el mismo subdirectorio
    inmediato que usa `FuenteLocal.listar_grupos()` para agrupar (ver su
    docstring); se recalcula acá porque `listar_grupos()` no expone la clave
    junto con el grupo ya armado."""
    directorio_raiz = directorio_raiz.resolve()
    return tuple(
        {
            "id_documento": f"{Path(artefacto.uri).relative_to(directorio_raiz).parts[0]}__{Path(artefacto.uri).stem}",
            "uri": artefacto.uri,
            "sha256": artefacto.sha256,
        }
        for artefacto in grupo_artefactos
    )


def _inicializar_trabajador_offline() -> None:
    """`initializer` de `ProcessPoolExecutor` para ESTE banco de medición --
    construye la fábrica de producción (`construir_fabrica_ejecutor`, la
    MISMA raíz de composición que usa `scripts/procesar_carpeta.py` y el
    banco de carga real) pero con los dobles de CPU
    (`_MotorPiiOffline`/`_DestinoMemoria`) en vez de spaCy/Postgres reales --
    igual filosofía que `tests/fixtures/corpus_piloto.py`: solo se
    sobrescribe lo que hace falta para correr en segundos, todo el resto del
    cableado (validación de episodio, observabilidad) es el real."""
    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(Path.cwd(),),  # no se usa: este banco no llama fuente.abrir() via ingesta real
        resolutor=object(),
        motor=_MotorPiiOffline(),
        pepper=PEPPER_MEDICION,
        destino=_DestinoMemoria(),
        cuarentena=_CuarentenaMemoria(),
        resolver_claves=_resolver_claves,
    )
    tareas.configurar_ejecutor(fabrica)


def _procesar_grupo_offline(corrida_id: str, grupo: Grupo) -> list[dict[str, object]]:
    return tareas.procesar_grupo(corrida_id, grupo)


def _medir_una_corrida(directorio_entrada: Path, *, procesos: int) -> float:
    fuente = FuenteLocal(raices=(directorio_entrada,), directorio=directorio_entrada, huellas=HuellasEnMemoria())
    grupos_referencias = [
        _referencias_de_grupo(grupo, directorio_raiz=directorio_entrada) for grupo in fuente.listar_grupos()
    ]

    inicio = time.perf_counter()
    if procesos <= 1:
        _inicializar_trabajador_offline()
        for grupo in grupos_referencias:
            tareas.procesar_grupo("medicion", grupo)
        tareas._fabrica_ejecutor = None
    else:
        cuarentena = _CuarentenaMemoria()
        despacho_paralelo.despachar_en_paralelo(
            corrida_id="medicion",
            grupos=iter(grupos_referencias),
            crear_pool=lambda: ProcessPoolExecutor(max_workers=procesos, initializer=_inicializar_trabajador_offline),
            procesos=procesos,
            cuarentena=cuarentena,
            funcion_trabajo=_procesar_grupo_offline,
        )
    return time.perf_counter() - inicio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pacientes", type=int, default=320, help="cantidad de grupos/pacientes sintéticos")
    parser.add_argument("--procesos", default="1,2,4", help="lista separada por comas de grados de concurrencia")
    args = parser.parse_args()

    niveles = [int(valor) for valor in args.procesos.split(",")]
    directorio_base = Path("tmp/medicion_escalado_paralelo")
    if directorio_base.exists():
        shutil.rmtree(directorio_base)
    directorio_base.mkdir(parents=True)

    print(f"Generando corpus sintético agrupado: {args.pacientes} pacientes...", file=sys.stderr)
    _generar_corpus_agrupado(directorio_base, pacientes=args.pacientes, semilla_base=20260907)

    print(f"{'procesos':>10} | {'segundos':>10} | {'speedup':>8}")
    tiempo_base = None
    for procesos in niveles:
        # `tareas` es un módulo global compartido con el proceso que corre este
        # `main()`: resetear la fábrica entre niveles evita que una corrida
        # secuencial previa dejara configurado un ejecutor con dobles de la
        # corrida anterior (no afecta a los hijos, que son procesos nuevos).
        tareas._fabrica_ejecutor = None
        segundos = _medir_una_corrida(directorio_base, procesos=procesos)
        if tiempo_base is None:
            tiempo_base = segundos
        speedup = tiempo_base / segundos
        print(f"{procesos:>10} | {segundos:>10.3f} | {speedup:>7.2f}x")

    shutil.rmtree(directorio_base, ignore_errors=True)


if __name__ == "__main__":
    main()
