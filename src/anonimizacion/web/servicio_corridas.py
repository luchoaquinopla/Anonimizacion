"""Implementación real de `rutas_corridas.ServicioCorridas` (design.md, "ServicioCorridas real").

`crear_corrida` delega en `LanzadorCorrida` para crear e inventariar, y en
`anonimizacion.trabajadores.despacho_paralelo.despachar_en_paralelo` (ya
existente, del PR 3 de `paralelismo-de-procesamiento`) para procesar el
inventario de verdad -- feature `despachador-desde-el-panel`: el despachador
de producción DEJA de estar fuera de alcance. El despacho corre en un HILO en
segundo plano (ver `_despachar_y_cerrar`): `crear_corrida` responde apenas
termina de inventariar, sin esperar horas de procesamiento.

`consultar_corrida` lee el embudo real y mapea `documentos_pendientes` /
`cuarentenas` desde ahí, así que conserva `EstadoCorridaPortal` y con él los
tests de ruta con dobles de prueba. `reintentar_corrida` lanza
`NotImplementedError`: la reanudación por documento está fuera de alcance, y
la ruta ya funciona hoy -- un `POST` real llegaría a su rama y devolvería un
202 sobre algo que no reintenta nada. El 501 hace visible el hueco en vez de
disimularlo.

Este módulo también arma el payload completo de `GET /corridas/{id}/embudo`
(`construir_payload_embudo`): NO es un método de `ServicioCorridas` -- esa
ruta no pasa por el resumen agregado de `EstadoCorridaPortal`, sirve el
contrato JSON completo del embudo (design.md, "El contrato JSON").
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
from anonimizacion.salida.modelos_orm import CorridaOrm
from anonimizacion.trabajadores import despacho_paralelo
from anonimizacion.web.embudo_corrida import Embudo, construir_embudo
from anonimizacion.web.rutas_corridas import EstadoCorridaPortal

Grupo = tuple[dict[str, str], ...]
# Misma forma que `despacho_paralelo.despachar_en_paralelo`: se acepta
# cualquier callable compatible (inyectado en tests que NO ejercitan el
# despacho en sí -- ver `_DespachadorFake` en
# `tests/web/test_servicio_corridas.py`), no sólo la función real.
FuncionDespacho = Callable[..., tuple[list[dict[str, object]], int, int]]


class CorridaEnCursoError(RuntimeError):
    """Ya hay otra corrida activa -- ver `ServicioCorridasReal.crear_corrida`.

    Decisión "dos corridas a la vez" (feature `despachador-desde-el-panel`):
    cada corrida despachada reserva su propio presupuesto de memoria (~875 MB
    medidos por proceso de `MotorPii`, `despacho_paralelo.py`) para
    `procesos` workers -- dos corridas concurrentes lo duplicarían sin que
    nada repartiera ese presupuesto entre ambas. Este panel es para UN
    operador (el codirector médico corriendo su propio corpus), no una cola
    multi-tenant: serializar corridas es la opción segura y la que coincide
    con el uso real, no una limitación aceptada a regañadientes.
    """

    def __init__(self, id_corrida_activa: str) -> None:
        self.id_corrida_activa = id_corrida_activa
        super().__init__(
            f"ya hay una corrida activa ({id_corrida_activa}) -- esperá a que termine antes de lanzar otra"
        )


def _despachar_y_cerrar(
    *,
    lanzador: LanzadorCorrida,
    corrida_id: str,
    grupos: Iterator[Grupo],
    entrada: Path,
    db_url: str,
    procesos: int,
    tope_bytes: int | None,
    despachador: FuncionDespacho,
) -> None:
    """Corre en un HILO en segundo plano, lanzado por `ServicioCorridasReal.crear_corrida`.

    Decisión "cómo no bloquear el servidor" (feature `despachador-desde-el-panel`):
    un HILO, no un `ProcessPoolExecutor` anidado ni un proceso nuevo. El
    trabajo pesado (CPU-bound: spaCy/Presidio por documento) YA corre en
    procesos hijos -- `despachador` (`despacho_paralelo.despachar_en_paralelo`)
    crea su propio `ProcessPoolExecutor` internamente, con `procesos`
    workers, exactamente como ya hace `scripts/procesar_carpeta.py::ejecutar`
    con `procesos>1`. Este hilo sólo ORQUESTA: llama al despachador y espera
    sus futuros -- I/O-bound desde la perspectiva de ESTE proceso, así que un
    hilo alcanza y no compite por el GIL con las demás peticiones HTTP que
    `wsgiref.simple_server` + `ThreadingMixIn` sigue atendiendo mientras
    tanto (`scripts/servir_panel.py`). Anidar OTRO `ProcessPoolExecutor`
    dentro de este hilo (o, peor, dentro de un proceso hijo) rompería el pool
    -- ver el docstring de `despacho_paralelo.py` sobre por qué esa lógica
    vive en un módulo real, pensado para invocarse desde un proceso servidor.

    Nunca se usa el camino SECUENCIAL de `procesar_carpeta.py` (`procesos<=1`
    llamando `tareas.procesar_grupo` en el mismo proceso): ese camino carga
    `MotorPii()` (~875 MB, spaCy) DENTRO del proceso del servidor y hace
    trabajo de CPU real bajo el GIL -- en un script de una sola corrida eso
    no importa, pero en un servidor que sigue sirviendo el panel a la vez
    congelaría toda otra petición HTTP mientras un documento se procesa.
    `despachar_en_paralelo` con `procesos=1` sigue usando un
    `ProcessPoolExecutor` de un solo worker -- un proceso hijo real, nunca el
    del servidor -- así que es seguro incluso con la concurrencia mínima.

    `marcar_procesando`/`marcar_finalizada`/`marcar_fallida` (feature
    `despachador-desde-el-panel`, `ingesta/lanzador_corrida.py`): quien
    REALMENTE procesa es quien tiene que afirmar y cerrar el estado -- éste
    es ese llamador. Un `Exception` INESPERADO (no una cuarentena por
    documento -- `despachar_en_paralelo` nunca propaga esas, quedan en
    `cuarentena`) marca la corrida `FALLIDA` en vez de dejarla `procesando`
    para siempre, y se vuelve a lanzar para que quede visible en stderr
    (`threading.excepthook` por defecto) -- no hay otro canal para un bug
    inesperado en un hilo de fondo.
    """
    try:
        lanzador.marcar_procesando(corrida_id)
        resultados, _total_documentos, _total_grupos = despachador(
            corrida_id=corrida_id,
            grupos=grupos,
            crear_pool=lambda n: despacho_paralelo.crear_pool_de_trabajadores(
                entrada=entrada,
                db_url=db_url,
                tope_bytes=tope_bytes,
                procesos=n,
            ),
            procesos=procesos,
            cuarentena=lanzador.cuarentena,
        )
    except Exception:
        try:
            lanzador.marcar_fallida(corrida_id)
        except Exception:
            pass  # ya hay una excepcion real en curso; no la tapamos con esta
        raise
    else:
        hubo_cuarentena = any(resultado["estado"] != "exito" for resultado in resultados)
        lanzador.marcar_finalizada(corrida_id, hubo_cuarentena=hubo_cuarentena)


def _leer_estado_corrida(motor: Engine, id_corrida: str) -> str | None:
    """Sólo el estado administrativo (`corrida.estado`, plano de control).

    No es la misma prohibición que la de `documento_corrida.estado`
    (design.md, Decisión 5): esa es la máquina de estados del DOCUMENTO,
    nunca leída por el embudo. Ésta es el estado de la CORRIDA, una fila
    única de plano de control, y es lo que expone el campo `"estado"` del
    contrato JSON.
    """
    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, id_corrida)
    return fila.estado if fila is not None else None


def _serializar_embudo(embudo: Embudo, estado: str) -> dict[str, object]:
    estimacion: dict[str, object] = {"situacion": embudo.estimacion.situacion}
    if embudo.estimacion.situacion == "disponible":
        estimacion["restante_seg_min"] = embudo.estimacion.restante_seg_min
        estimacion["restante_seg_max"] = embudo.estimacion.restante_seg_max
    return {
        "corrida_id": embudo.corrida_id,
        "estado": estado,
        "generado_en": embudo.generado_en.isoformat(),
        "entraron": embudo.entraron,
        "publicados": embudo.publicados,
        "apartados": embudo.apartados,
        "residuo": embudo.residuo,
        "cierra": embudo.cierra,
        "marcha": embudo.marcha,
        "etapas": [
            {
                "etapa": perdida.etapa,
                "llegaron": perdida.llegaron,
                "apartados": perdida.apartados,
                "codigos": dict(perdida.codigos),
            }
            for perdida in embudo.etapas
        ],
        "throughput_por_hora": dict(embudo.throughput_por_hora),
        "estimacion": estimacion,
    }


def construir_payload_embudo(motor: Engine, id_corrida: str) -> dict[str, object] | None:
    """`None` si la corrida no existe -- la ruta lo traduce a 404."""
    estado = _leer_estado_corrida(motor, id_corrida)
    if estado is None:
        return None
    embudo = construir_embudo(motor, id_corrida)
    return _serializar_embudo(embudo, estado)


@dataclass(frozen=True)
class ServicioCorridasReal:
    """Implementación real: crea, despacha y consulta el embudo de verdad.

    `db_url`: cada proceso hijo de `despacho_paralelo.crear_pool_de_trabajadores`
    arma su PROPIO `Engine` de Postgres (una conexión de socket no sobrevive
    un pickle a través del límite de proceso) -- este servicio necesita la
    URL, no sólo el `Engine` ya conectado que usa para leer.

    `procesos`: grado de concurrencia de CADA corrida despachada desde este
    servicio -- mismo significado que `--procesos` en
    `scripts/procesar_carpeta.py` (`despacho_paralelo.validar_grado_concurrencia`
    en el llamador de producción, `scripts/servir_panel.py`, valida el rango
    antes de construir este servicio).

    `despachador`: el despachador REAL por defecto
    (`despacho_paralelo.despachar_en_paralelo`) -- inyectable sólo para tests
    que no ejercitan el despacho en sí (ver `FuncionDespacho` arriba).
    Producción nunca lo overridea.

    `_hilos_en_curso`: mutado en el lugar (nunca reasignado, mismo convenio
    que `MetricasDespacho` en `despacho_paralelo.py`) -- registra los hilos
    de despacho lanzados por `crear_corrida` para que
    `esperar_despachos_en_curso` pueda esperarlos (tests de integración HTTP
    que necesitan el resultado final de un despacho real antes de
    comprobarlo, y el cierre ordenado de `scripts/servir_panel.py`).
    """

    lanzador: LanzadorCorrida
    motor: Engine
    db_url: str
    procesos: int
    tope_bytes: int | None = None
    despachador: FuncionDespacho = despacho_paralelo.despachar_en_paralelo
    _hilos_en_curso: list[threading.Thread] = field(default_factory=list)

    def crear_corrida(self, ruta_autorizada: str) -> EstadoCorridaPortal:
        """Crea la corrida, inventaría el primer grupo, y despacha el resto
        en SEGUNDO PLANO -- feature `despachador-desde-el-panel`: el
        despachador de producción deja de estar fuera de alcance.

        Decisión "una corrida a la vez": antes de tocar nada, rechaza si ya
        hay otra corrida activa (`CorridaEnCursoError` -- la ruta la traduce
        a `409`, ver `web/rutas_corridas.py`). Ver el docstring de
        `CorridaEnCursoError` para el porqué.

        `LanzadorCorrida.lanzar().referencias` es un generador de UN SOLO USO
        (openspec `paralelismo-de-procesamiento` PR 2, revisión adversarial
        hallazgo crítico 2). Antes, este método drenaba el generador COMPLETO
        acá mismo, en el hilo de la petición HTTP, sólo para forzar el
        registro del inventario -- y descartaba el resultado a propósito
        (nada más lo consumía). Eso es exactamente lo que `procesar_carpeta.py::ejecutar`
        NO hace: ahí sólo se extrae el PRIMER grupo con `next(..., None)`
        (para poder responder rápido y detectar "no hay nada que procesar"
        sin materializar la corrida entera), y el resto se encadena
        perezosamente (`itertools.chain`) hacia el despachador real. Este
        método sigue ese mismo patrón: el primer grupo se inventaría en el
        hilo de la petición (rápido comparado con horas de PII, igual que ya
        acepta el script), y el resto se inventaría/despacha en el hilo de
        fondo, a medida que `despachador` va consumiendo el iterador.

        Si no hay ningún grupo (carpeta sin PDFs), no se lanza ningún hilo --
        no hay nada que procesar (misma decisión que el script).
        """
        activas = self.lanzador.repositorio.listar_corridas_no_terminales()
        if activas:
            raise CorridaEnCursoError(activas[0].id_corrida)

        ruta = Path(ruta_autorizada)
        resultado = self.lanzador.lanzar(ruta)
        iterador_grupos = iter(resultado.referencias)
        primer_grupo = next(iterador_grupos, None)
        if primer_grupo is not None:
            grupos_a_despachar = itertools.chain([primer_grupo], iterador_grupos)
            hilo = threading.Thread(
                target=_despachar_y_cerrar,
                kwargs={
                    "lanzador": self.lanzador,
                    "corrida_id": resultado.corrida_id,
                    "grupos": grupos_a_despachar,
                    "entrada": ruta,
                    "db_url": self.db_url,
                    "procesos": self.procesos,
                    "tope_bytes": self.tope_bytes,
                    "despachador": self.despachador,
                },
                # `daemon=True`: si el servidor se cae (o Ctrl+C) con una
                # corrida en curso, este hilo muere con el proceso -- no
                # queda colgando el apagado. La corrida queda `procesando`
                # hasta el próximo arranque, donde
                # `lanzador_corrida.recuperar_corridas_abandonadas` la cierra
                # `FALLIDA` (decisión "qué pasa si el servidor se cae",
                # `scripts/servir_panel.py`). No es un dato perdido: los
                # documentos ya escritos en `estudio`/`cuarentena` antes de
                # la caída no se revierten, sólo el renglón administrativo
                # de `corrida` se cierra honesto.
                daemon=True,
            )
            self._hilos_en_curso.append(hilo)
            hilo.start()
        return self.consultar_corrida(resultado.corrida_id)

    def esperar_despachos_en_curso(self, timeout: float | None = None) -> None:
        """Bloquea hasta que todos los despachos en segundo plano lanzados
        por ESTE servicio terminen (o hasta `timeout`, por hilo).

        Dos llamadores: tests de integración HTTP que necesitan observar el
        resultado FINAL de un despacho real antes de comprobarlo (no pueden
        depender de que la corrida ya haya terminado apenas
        `crear_corrida` devuelve -- ésa es justo la propiedad que este
        cambio introduce), y el cierre ordenado de
        `scripts/servir_panel.py::main` ante `KeyboardInterrupt`, best-effort
        antes de cerrar el servidor.
        """
        for hilo in list(self._hilos_en_curso):
            hilo.join(timeout=timeout)

    def consultar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
        estado = _leer_estado_corrida(self.motor, id_corrida)
        embudo = construir_embudo(self.motor, id_corrida)
        return EstadoCorridaPortal(
            id_corrida=id_corrida,
            estado=estado or "desconocida",
            # `sin_desenlace` es el mismo residuo con signo del embudo
            # (design.md, Decisión 9): no se recorta acá tampoco -- un
            # descuadre en la corrida real tiene que verse en este resumen
            # agregado igual que en el JSON completo.
            documentos_pendientes=embudo.residuo,
            cuarentenas=embudo.apartados,
        )

    def reintentar_corrida(self, id_corrida: str) -> EstadoCorridaPortal:
        raise NotImplementedError(
            "reintentar_corrida: la reanudacion por documento esta fuera de alcance de "
            "panel-de-operacion (design.md, 'ServicioCorridas real')"
        )
