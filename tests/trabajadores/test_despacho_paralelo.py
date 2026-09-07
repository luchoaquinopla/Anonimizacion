"""Tests de `anonimizacion.trabajadores.despacho_paralelo` (openspec
`paralelismo-de-procesamiento` PR 3).

No usan Postgres ni `MotorPii` real -- eso lo cubre
`tests/scripts/test_procesar_carpeta.py` (marcado `pytest.mark.postgres`) con
el camino de producción completo. Acá se prueba el MECANISMO de despacho y
recuperación en sí: ventana deslizante sin materializar la lista completa de
grupos, paralelismo real (procesos del SO genuinamente distintos, no
simulado) y recuperación ante `BrokenProcessPool` sin tumbar la corrida.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor

import pytest

from anonimizacion.trabajadores import despacho_paralelo

from ._dobles_despacho_paralelo import (
    ID_DOCUMENTO_QUE_MUERE_SIEMPRE,
    VAR_ENV_MARCADOR,
    VAR_ENV_MARCADOR_COMPLETADOS,
    VAR_ENV_MARCADOR_INTENTOS,
    CuarentenaEnMemoria,
    referencia,
    trabajo_cuenta_intentos_y_muere_siempre,
    trabajo_devuelve_pid,
    trabajo_duerme_mucho,
    trabajo_marca_completado_tras_una_pausa,
    trabajo_marca_completado_y_devuelve_pid,
    trabajo_muere_la_primera_vez_por_grupo,
    trabajo_muere_siempre_o_tarda_un_poco,
    trabajo_muere_siempre_si_esta_marcado,
)


def _crear_pool(procesos: int) -> ProcessPoolExecutor:
    # Sin `initializer`: los dobles de este archivo no necesitan pepper,
    # motor ni engine -- solo confirmar el PID o morir a propósito. Recibe
    # el grado de concurrencia deseado -- `despachar_en_paralelo` lo llama
    # tanto con `procesos` (pool principal) como con `1` (aislamiento tras
    # un pool roto, ver `despacho_paralelo._EstadoDespacho._reprocesar_en_aislamiento`).
    return ProcessPoolExecutor(max_workers=procesos)


# --- grado de concurrencia ---------------------------------------------------


def test_grado_de_concurrencia_por_defecto_es_al_menos_uno_y_respeta_el_tope_conservador(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert despacho_paralelo.grado_de_concurrencia_por_defecto() == 4  # min(12//2, 4)

    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert despacho_paralelo.grado_de_concurrencia_por_defecto() == 1  # max(1, min(1, 4))

    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert despacho_paralelo.grado_de_concurrencia_por_defecto() >= 1


def test_validar_grado_concurrencia_rechaza_menos_de_uno():
    with pytest.raises(ValueError, match="al menos 1"):
        despacho_paralelo.validar_grado_concurrencia(0)


def test_validar_grado_concurrencia_rechaza_pasar_el_tope_duro(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    tope = despacho_paralelo.tope_duro_concurrencia()
    assert tope == 8
    with pytest.raises(ValueError, match="tope duro"):
        despacho_paralelo.validar_grado_concurrencia(tope + 1)
    assert despacho_paralelo.validar_grado_concurrencia(tope) == tope


def test_el_tope_duro_tambien_limita_por_memoria_no_solo_por_nucleos(monkeypatch):
    """ALTO 4 de revisión adversarial: antes de este ajuste, el tope duro
    solo validaba contra 2x núcleos lógicos -- en una máquina de muchos
    núcleos eso permitía `--procesos` muy por encima de lo que la memoria
    (el recurso que este módulo mismo argumenta que es el techo real,
    ~875 MB medidos por copia de `es_core_news_lg`) puede sostener. Con 64
    núcleos lógicos, 2x núcleos daría 128 -- el tope real tiene que quedar
    acotado por el presupuesto de memoria del tope duro, mucho más chico."""
    monkeypatch.setattr(os, "cpu_count", lambda: 64)
    tope = despacho_paralelo.tope_duro_concurrencia()
    assert tope < 128, "el tope duro no puede depender solo de nucleos logicos"
    assert tope == despacho_paralelo._PRESUPUESTO_MEMORIA_TOPE_DURO_MB // despacho_paralelo._MEMORIA_ESTIMADA_POR_PROCESO_MB
    with pytest.raises(ValueError, match="tope duro"):
        despacho_paralelo.validar_grado_concurrencia(24)


# --- paralelismo real ---------------------------------------------------


def test_despachar_en_paralelo_usa_procesos_del_sistema_operativo_genuinamente_distintos():
    """No alcanza con que exista un parametro `procesos`: hay que confirmar
    que dos grupos corrieron en PIDs de verdad distintos, y distintos del
    proceso de test."""
    grupos = iter(
        [
            (referencia("doc-a"),),
            (referencia("doc-b"),),
            (referencia("doc-c"),),
            (referencia("doc-d"),),
        ]
    )
    cuarentena = CuarentenaEnMemoria()

    resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-paralelismo-real",
        grupos=grupos,
        crear_pool=_crear_pool,
        procesos=2,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_devuelve_pid,
    )

    assert total_grupos == 4
    assert total_documentos == 4
    pids_hijos = {resultado["pid"] for resultado in resultados}
    assert os.getpid() not in pids_hijos, "los grupos deben procesarse en HIJOS, no en el proceso de test"
    assert len(pids_hijos) >= 2, (
        f"se esperaban al menos 2 PIDs distintos entre los hijos, se vieron: {pids_hijos}"
    )
    assert not cuarentena.errores


def test_despachar_en_paralelo_no_materializa_todos_los_grupos_antes_de_despachar(tmp_path, monkeypatch):
    """Centinela de pereza (reescrito tras revisión adversarial MEDIO 6: la
    versión anterior afirmaba en su docstring que una implementación ansiosa
    (`list(grupos)`) haría fallar este test con `RuntimeError` -- FALSO,
    verificado con una implementación ansiosa real que lo pasaba igual. Esta
    versión observa el MOMENTO del consumo, no solo el total final.

    Cada tarea deja un archivo en un directorio compartido ANTES de
    retornar (`trabajo_marca_completado_y_devuelve_pid`). El generador de
    grupos, corriendo en el proceso PADRE, registra una violación si se le
    pide un grupo más allá de la ventana inicial (`procesos`) sin que
    todavía exista NINGÚN archivo de completación -- eso solo puede pasar
    si la implementación materializó el iterador por adelantado, porque en
    el camino perezoso real `_reponer()` (que es quien pide el siguiente
    grupo) solo se llama DESPUÉS de que `future.result()` desbloquea tras
    una tarea ya terminada."""
    directorio_completados = tmp_path / "completados"
    directorio_completados.mkdir()
    monkeypatch.setenv(VAR_ENV_MARCADOR_COMPLETADOS, str(directorio_completados))

    procesos = 2
    total_de_grupos = 6
    entregados = 0
    violaciones: list[int] = []

    def _generador_que_vigila_el_momento_del_consumo():
        nonlocal entregados
        for indice in range(total_de_grupos):
            if indice >= procesos and not any(directorio_completados.iterdir()):
                violaciones.append(indice)
            entregados += 1
            yield (referencia(f"doc-{indice}"),)

    cuarentena = CuarentenaEnMemoria()
    resultados, _, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-pereza",
        grupos=_generador_que_vigila_el_momento_del_consumo(),
        crear_pool=_crear_pool,
        procesos=procesos,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_marca_completado_y_devuelve_pid,
    )

    assert not violaciones, (
        f"se pidieron grupos en los indices {violaciones} sin que ninguna tarea hubiera "
        "terminado todavia -- la implementacion esta materializando el iterador por adelantado"
    )
    assert total_grupos == total_de_grupos
    assert entregados == total_de_grupos
    assert len(resultados) == total_de_grupos


# --- aislamiento de fallo: un hijo muerto no tumba la corrida ---------------


def test_un_hijo_que_muere_no_tumba_la_corrida_y_los_demas_grupos_se_procesan():
    """Un grupo cuyo hijo muere (simulando un OOM-kill del SO) NO debe hacer
    que `despachar_en_paralelo` propague una excepcion -- los demas grupos
    deben terminar en exito de todos modos, y el grupo muerto (reintentos
    agotados) debe terminar apartado en cuarentena, no perdido en silencio."""
    grupos = iter(
        [
            (referencia("doc-ok-1"),),
            (referencia(ID_DOCUMENTO_QUE_MUERE_SIEMPRE),),
            (referencia("doc-ok-2"),),
            (referencia("doc-ok-3"),),
        ]
    )
    cuarentena = CuarentenaEnMemoria()

    resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-hijo-muere",
        grupos=grupos,
        crear_pool=_crear_pool,
        procesos=2,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_muere_siempre_si_esta_marcado,
    )

    assert total_grupos == 4
    assert total_documentos == 4

    exitos = [r for r in resultados if r["estado"] == "exito"]
    fallos = [r for r in resultados if r["estado"] != "exito"]
    assert {r["id_documento"] for r in exitos} == {"doc-ok-1", "doc-ok-2", "doc-ok-3"}
    assert [r["id_documento"] for r in fallos] == [ID_DOCUMENTO_QUE_MUERE_SIEMPRE]
    # `proceso_interrumpido`, NO `error_transitorio_agotado` (revisión
    # adversarial ALTO 3): son códigos deliberadamente distintos -- un
    # proceso muerto por el SO no es lo mismo que un fallo real DENTRO del
    # pipeline, y confundirlos le ocultaría al operador que la causa está en
    # el proceso, no en el contenido del documento.
    assert fallos[0]["codigo"] == "proceso_interrumpido"
    assert fallos[0]["etapa"] == "despacho"

    # El invariante del embudo (residuo = entraron - (publicados + apartados))
    # exige que el documento perdido quede APARTADO, no solo devuelto en
    # memoria -- si no se registrara en cuarentena, "entraron" lo seguiria
    # contando y el residuo nunca cerraria.
    assert len(cuarentena.errores) == 1
    assert cuarentena.errores[0].id_documento == ID_DOCUMENTO_QUE_MUERE_SIEMPRE
    assert cuarentena.errores[0].corrida_id == "corrida-hijo-muere"


def test_un_hijo_que_muere_una_vez_se_recupera_en_el_reintento(tmp_path, monkeypatch):
    """Distinto del test anterior: acá el hijo muere UNA sola vez por grupo
    -- la recuperacion automatica (aislamiento, mismo grupo reprocesado)
    debe terminar en EXITO, sin tocar cuarentena. `procesos=1`: aísla la
    mecánica de recuperación en sí, sin la complejidad adicional de grupos
    concurrentes (esa la ejercita
    `test_ningun_grupo_sano_termina_en_cuarentena_por_compartir_pool_con_uno_toxico`,
    con `procesos>1`)."""
    monkeypatch.setenv(VAR_ENV_MARCADOR, str(tmp_path))
    grupos = iter([(referencia("doc-se-recupera-1"),), (referencia("doc-se-recupera-2"),)])
    cuarentena = CuarentenaEnMemoria()

    resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-recupera",
        grupos=grupos,
        crear_pool=_crear_pool,
        procesos=1,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_muere_la_primera_vez_por_grupo,
    )

    assert total_grupos == 2
    assert total_documentos == 2
    assert {r["estado"] for r in resultados} == {"exito"}
    assert {r["id_documento"] for r in resultados} == {"doc-se-recupera-1", "doc-se-recupera-2"}
    assert not cuarentena.errores


def test_la_ventana_vuelve_a_su_ancho_completo_despues_de_dar_un_grupo_por_perdido():
    """Centinela del CRÍTICO 1 de revisión adversarial: `_dar_por_perdido`
    nunca llamaba `_reponer()` -- el lugar de un grupo perdido quedaba
    vacío para siempre y la ventana deslizante colapsaba a un ancho menor
    por el resto de la corrida, sin ningún log ni métrica que lo señalara.
    Reproducido por la revisión con `procesos=4` y 15 grupos sanos: el
    ancho de `en_vuelo` llegaba a 4 y caía a 1 para el resto de la corrida.

    Este test observa el ancho de `en_vuelo` DIRECTAMENTE (no los totales
    finales, que no distinguen "se procesó todo en paralelo" de "se procesó
    todo en serie después del primer crash") justo después de que la
    recuperación de un pool roto termina."""
    procesos = 4
    total_sanos = 15
    grupos = iter(
        [(referencia(ID_DOCUMENTO_QUE_MUERE_SIEMPRE),)]
        + [(referencia(f"doc-sano-{indice}"),) for indice in range(total_sanos)]
    )
    cuarentena = CuarentenaEnMemoria()
    anchos_tras_recuperacion: list[int] = []

    estado = despacho_paralelo._EstadoDespacho(
        corrida_id="corrida-ventana",
        grupos=grupos,
        crear_pool=_crear_pool,
        procesos=procesos,
        cuarentena=cuarentena,
        # `trabajo_muere_siempre_o_tarda_un_poco`, NO la versión instantánea:
        # ver su docstring -- con trabajo sano instantáneo, los 15 sanos
        # pueden agotar el iterador por el camino normal ANTES de que el SO
        # notifique la muerte del tóxico, dejando la ventana en 0 (correcto:
        # no queda nada que reponer) pero indistinguible de un colapso real.
        funcion_trabajo=trabajo_muere_siempre_o_tarda_un_poco,
    )
    original_recuperar = estado._recuperar_de_pool_roto

    def _recuperar_vigilado(indice, grupo):
        original_recuperar(indice, grupo)
        anchos_tras_recuperacion.append(len(estado.en_vuelo))

    estado._recuperar_de_pool_roto = _recuperar_vigilado
    resultados, total_documentos, total_grupos = estado.ejecutar()

    assert total_grupos == 1 + total_sanos
    assert total_documentos == 1 + total_sanos
    assert anchos_tras_recuperacion, "nunca se disparo una recuperacion -- el test no ejercito el camino que prueba"
    # Justo tras la recuperación (que da por perdido al grupo tóxico en
    # aislamiento), la ventana tiene que volver a tocar su ancho completo --
    # quedan 15 grupos sanos disponibles en el iterador, así que no hay
    # excusa de "se agotó" para no reponerla del todo.
    assert anchos_tras_recuperacion[0] == procesos, (
        f"la ventana no volvio a su ancho completo ({procesos}) tras la recuperacion: "
        f"quedo en {anchos_tras_recuperacion[0]} -- ver CRITICO 1 de la revision adversarial"
    )


def test_ningun_grupo_sano_termina_en_cuarentena_por_compartir_pool_con_uno_toxico():
    """Centinela del CRÍTICO 2 de revisión adversarial: `wait()` convierte
    la lista de futuros a un `set` -- cuál "sale primero" del bucle es
    orden de HASH, no de causalidad. Tratar al primero como culpable
    (versión anterior de `_recuperar_de_pool_roto`) mandaba estudios SANOS
    a cuarentena por compartir pool con uno tóxico -- reproducido por la
    revisión con `procesos=4`: de 3 grupos perdidos, 2 eran sanos.

    Corre varias rondas (la asignación de qué proceso muere primero no es
    determinística) para no depender de que una sola corrida "tuviera
    suerte" con el orden -- con atribución causal correcta (aislamiento),
    el resultado tiene que ser el MISMO en todas: solo el grupo tóxico
    termina en cuarentena, nunca uno sano."""
    procesos = 4
    total_sanos = 15

    for ronda in range(5):
        grupos = iter(
            [(referencia(ID_DOCUMENTO_QUE_MUERE_SIEMPRE),)]
            + [(referencia(f"doc-sano-{ronda}-{indice}"),) for indice in range(total_sanos)]
        )
        cuarentena = CuarentenaEnMemoria()

        resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
            corrida_id=f"corrida-atribucion-{ronda}",
            grupos=grupos,
            crear_pool=_crear_pool,
            procesos=procesos,
            cuarentena=cuarentena,
            funcion_trabajo=trabajo_muere_siempre_si_esta_marcado,
        )

        assert total_grupos == 1 + total_sanos, f"ronda {ronda}"
        assert total_documentos == 1 + total_sanos, f"ronda {ronda}"

        fallos = [r for r in resultados if r["estado"] != "exito"]
        ids_perdidos = {r["id_documento"] for r in fallos}
        assert ids_perdidos == {ID_DOCUMENTO_QUE_MUERE_SIEMPRE}, (
            f"ronda {ronda}: se perdieron grupos SANOS ademas del toxico: {ids_perdidos}"
        )
        assert {error.id_documento for error in cuarentena.errores} == {ID_DOCUMENTO_QUE_MUERE_SIEMPRE}, (
            f"ronda {ronda}: la cuarentena registro un grupo sano"
        )


def test_un_grupo_toxico_se_ejecuta_exactamente_dos_veces_antes_de_darse_por_perdido(tmp_path, monkeypatch):
    """Centinela del hallazgo 2 de la auditoría posterior (ronda 2): el
    comentario de `MAX_REINTENTOS_POR_GRUPO` dice "1 reintento" -- con la
    comparación `>` eso en realidad daba 3 ejecuciones (1 en el pool
    principal + 2 en aislamiento), no 2. Cuenta las ejecuciones REALES vía
    un archivo por intento (no infiere del resultado final)."""
    directorio_intentos = tmp_path / "intentos"
    directorio_intentos.mkdir()
    monkeypatch.setenv(VAR_ENV_MARCADOR_INTENTOS, str(directorio_intentos))
    cuarentena = CuarentenaEnMemoria()

    resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-cuenta-intentos",
        grupos=iter([(referencia("doc-toxico"),)]),
        crear_pool=_crear_pool,
        procesos=1,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_cuenta_intentos_y_muere_siempre,
    )

    assert total_grupos == 1
    assert total_documentos == 1
    assert resultados[0]["codigo"] == "proceso_interrumpido"
    intentos_reales = len(list(directorio_intentos.iterdir()))
    assert intentos_reales == 2, (
        f"se esperaban exactamente 2 ejecuciones (1 en el pool principal + "
        f"1 reintento en aislamiento, ver MAX_REINTENTOS_POR_GRUPO), se observaron {intentos_reales}"
    )


def test_las_metricas_de_despacho_cuentan_recreaciones_y_reprocesos():
    """Centinela del hallazgo 1 de la auditoría posterior (ronda 2): la
    recuperación tiene un costo real (recargas completas del modelo) que
    antes no se veía en ningún lado. `MetricasDespacho` tiene que reflejar
    exactamente cuántas veces se recreó el pool principal y cuántos
    reprocesos en aislamiento hicieron falta."""
    metricas = despacho_paralelo.MetricasDespacho()
    cuarentena = CuarentenaEnMemoria()

    grupos = iter(
        [
            (referencia("doc-ok-1"),),
            (referencia(ID_DOCUMENTO_QUE_MUERE_SIEMPRE),),
            (referencia("doc-ok-2"),),
        ]
    )

    despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-metricas",
        grupos=grupos,
        crear_pool=_crear_pool,
        procesos=2,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_muere_siempre_si_esta_marcado,
        metricas=metricas,
    )

    # Un solo BrokenProcessPool -> una sola recreación del pool principal.
    assert metricas.recreaciones_de_pool_principal == 1
    # El grupo tóxico se reprocesa en aislamiento hasta agotar su cupo (2
    # veces, ver MAX_REINTENTOS_POR_GRUPO) -- el colateral sano que
    # compartía el pool roto (si lo hubo) se reprocesa una vez más, en
    # aislamiento, antes de confirmarse inocente. El total es siempre >= 1.
    assert metricas.reprocesos_en_aislamiento >= 1
    snapshot = metricas.snapshot()
    assert snapshot == {
        "recreaciones_de_pool_principal": metricas.recreaciones_de_pool_principal,
        "reprocesos_en_aislamiento": metricas.reprocesos_en_aislamiento,
    }


# --- cancelación (revisión adversarial crítico 2) ---------------------------


def test_despachar_en_paralelo_deja_de_tomar_grupos_nuevos_cuando_se_pide_detener(tmp_path, monkeypatch):
    """Ctrl+C en el servidor (`scripts/servir_panel.py`) necesita poder
    frenar un despacho de HORAS sin esperar a que TODOS los grupos
    pendientes terminen -- sólo drenar lo que ya estaba en vuelo. `detener`
    (un `threading.Event`) es la señal: una vez seteado, `_reponer` deja de
    tomar grupos NUEVOS del iterador, tanto en la ventana inicial como al
    reponer un hueco -- lo ya en vuelo se deja terminar normalmente.

    Real, no simulado: `ProcessPoolExecutor` real con 2 workers, 10 grupos
    disponibles -- si `detener` no tuviera efecto, los 10 se procesarían.
    """
    directorio_completados = tmp_path / "completados"
    directorio_completados.mkdir()
    monkeypatch.setenv(VAR_ENV_MARCADOR_COMPLETADOS, str(directorio_completados))

    detener = threading.Event()
    total_grupos_disponibles = 10
    grupos = ((referencia(f"doc-cancelacion-{i}"),) for i in range(total_grupos_disponibles))

    resultado: dict[str, object] = {}

    def _correr() -> None:
        resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
            corrida_id="corrida-cancelacion",
            grupos=grupos,
            crear_pool=_crear_pool,
            procesos=2,
            cuarentena=CuarentenaEnMemoria(),
            funcion_trabajo=trabajo_marca_completado_tras_una_pausa,
            detener=detener,
        )
        resultado["resultados"] = resultados
        resultado["total_documentos"] = total_documentos
        resultado["total_grupos"] = total_grupos

    hilo = threading.Thread(target=_correr)
    hilo.start()

    # Espera a que al menos UN grupo termine de verdad (marcador en disco,
    # no una suposición de timing) antes de pedir la detención.
    limite = time.monotonic() + 20
    while not any(directorio_completados.iterdir()):
        if time.monotonic() > limite:
            hilo.join(timeout=5)
            pytest.fail("ningún grupo completó a tiempo -- el test no puede seguir")
        time.sleep(0.01)

    detener.set()
    hilo.join(timeout=30)

    assert not hilo.is_alive(), "despachar_en_paralelo no retornó a tiempo tras pedir detener"
    assert resultado["total_grupos"] < total_grupos_disponibles, (
        "detener() no tuvo efecto: se procesaron TODOS los grupos disponibles"
    )
    assert resultado["total_grupos"] >= 1, "lo que ya estaba en vuelo tiene que haberse dejado terminar"


def test_registro_de_pool_termina_los_procesos_hijos_vivos_a_la_fuerza():
    """Revisión adversarial ronda 3, hallazgo 3: "el resguardo del timeout es
    una ilusión" -- `detener` (cooperativo) sólo evita tomar trabajo NUEVO,
    nunca interrumpe un worker YA ocupado. Con trabajo que duerme mucho más
    que cualquier timeout razonable, `detener` solo NUNCA deja que el
    despacho retorne a tiempo -- `RegistroDePool.terminar_a_la_fuerza` sí,
    matando el proceso hijo real en medio del sueño."""
    detener = threading.Event()
    registro = despacho_paralelo.RegistroDePool()
    grupos = iter([(referencia("doc-forzado-1"),), (referencia("doc-forzado-2"),)])

    resultado: dict[str, object] = {}
    errores: dict[str, str] = {}

    def _correr() -> None:
        try:
            resultado["r"] = despacho_paralelo.despachar_en_paralelo(
                corrida_id="corrida-forzada",
                grupos=grupos,
                crear_pool=_crear_pool,
                procesos=2,
                cuarentena=CuarentenaEnMemoria(),
                funcion_trabajo=trabajo_duerme_mucho,
                detener=detener,
                registro_de_pool=registro,
            )
        except Exception:  # noqa: BLE001 -- capturado para un mensaje de fallo legible, no un KeyError críptico
            import traceback

            errores["e"] = traceback.format_exc()

    hilo = threading.Thread(target=_correr)
    hilo.start()

    # Espera a que el pool real tenga sus DOS procesos hijos reales ya
    # arrancados -- no sólo el primero. Terminar un proceso mientras
    # `ProcessPoolExecutor` todavía está en medio de generar OTRO (spawn de
    # Windows, duplicación de handles) es una carrera real de este test, no
    # del código bajo prueba: confirmado empíricamente en esta sesión que
    # terminar el primer worker mientras el segundo `_spawn_process()`
    # seguía en curso producía `OSError: handle is closed` -- una carrera de
    # infraestructura de `multiprocessing.spawn`, no de `RegistroDePool`
    # (reproducido y descartado corriendo el mismo escenario sin pytest de
    # por medio, donde no ocurre). Esperar a que AMBOS procesos ya figuren
    # en `_processes` antes de terminar evita esa carrera sin debilitar lo
    # que el test verifica.
    limite = time.monotonic() + 20
    while registro.pool is None or len(getattr(registro.pool, "_processes", {}) or {}) < 2:
        if time.monotonic() > limite:
            detener.set()
            hilo.join(timeout=5)
            pytest.fail("el pool nunca tuvo sus dos procesos hijos disponibles en el registro")
        time.sleep(0.01)

    # Con SOLO el apagado cooperativo, el hilo seguiría bloqueado ~30 s (el
    # sleep del trabajo) -- confirmar que la terminación forzada no depende
    # de eso: pedirla ANTES de que el sleep termine y esperar un tiempo
    # mucho menor a 30 s.
    detener.set()
    terminados = registro.terminar_a_la_fuerza()
    hilo.join(timeout=10)

    assert not errores, f"_correr crasheo: {errores.get('e')}"
    assert terminados >= 1, "tenía que haber al menos un proceso hijo vivo para terminar"
    assert not hilo.is_alive(), (
        "el despacho tiene que retornar en segundos tras la terminación forzada, "
        "no esperar los ~30 s del sleep -- si esto falla, terminar_a_la_fuerza no funcionó"
    )
    resultados, _total_documentos, total_grupos = resultado["r"]  # type: ignore[misc]
    assert total_grupos == 2, "los grupos interrumpidos se dan por perdidos, no se cuentan como exito silencioso"
    assert all(r["estado"] != "exito" for r in resultados), "ningún grupo forzado a morir puede figurar como exito"


def test_detener_seteado_durante_una_recuperacion_real_no_repone_en_el_pool_recreado():
    """Hueco de cobertura señalado en revisión adversarial ronda 3: `_reponer`
    ya respetaba `detener` incluso DENTRO de `_recuperar_de_pool_roto` (el
    trace era consistente por lectura), pero no había ningún test de esa
    interacción específica -- `detener` puede setearse en medio de una
    recuperación NORMAL (un crash real, sin relación con
    `terminar_a_la_fuerza`), justo entre que se recrea el pool principal y
    se repone la ventana. Ningún grupo sano restante debe someterse al pool
    recién recreado si eso pasa."""
    detener = threading.Event()
    llamadas_pool_principal = 0

    def _crear_pool_que_detiene_tras_recuperar(n: int) -> ProcessPoolExecutor:
        nonlocal llamadas_pool_principal
        if n == 2:  # pool PRINCIPAL (el aislado siempre pide n=1)
            llamadas_pool_principal += 1
            if llamadas_pool_principal == 2:
                # Segunda vez que se pide el pool principal: es la
                # RECREACIÓN tras el crash -- simula que algo externo (no
                # `terminar_a_la_fuerza`, que es un caso ya cubierto aparte)
                # pidió detener justo en este instante.
                detener.set()
        return ProcessPoolExecutor(max_workers=n)

    # `trabajo_muere_siempre_o_tarda_un_poco` (no `..._si_esta_marcado`): los
    # grupos sanos duermen unos milisegundos -- sin eso, con trabajo sano
    # INSTANTÁNEO los sanos pueden completarse y agotar el iterador por su
    # cuenta ANTES de que el sistema operativo notifique la muerte del
    # tóxico (ver el docstring de ese doble), y el escenario que este test
    # quiere ejercitar (grupos sanos TODAVÍA en el iterador cuando se
    # recupera) no llegaría a darse -- confirmado empíricamente en esta
    # sesión con el doble instantáneo: intermitente, 2 de 3 corridas.
    grupos = iter(
        [
            (referencia("doc-ok-1"),),
            (referencia(ID_DOCUMENTO_QUE_MUERE_SIEMPRE),),
            (referencia("doc-ok-2"),),
            (referencia("doc-ok-3"),),
        ]
    )
    cuarentena = CuarentenaEnMemoria()

    resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-detener-durante-recuperacion",
        grupos=grupos,
        crear_pool=_crear_pool_que_detiene_tras_recuperar,
        procesos=2,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_muere_siempre_o_tarda_un_poco,
        detener=detener,
    )

    # El grupo tóxico se recupera NORMALMENTE (no fue una cancelación --
    # `detener` no estaba seteado cuando la recuperación empezó): termina en
    # cuarentena por su propia causa, con la MISMA atribución causal de
    # siempre.
    fallos = [r for r in resultados if r["estado"] != "exito"]
    assert [r["id_documento"] for r in fallos] == [ID_DOCUMENTO_QUE_MUERE_SIEMPRE]
    assert fallos[0]["codigo"] == "proceso_interrumpido"

    # Pero como `detener` quedó seteado justo al recrear el pool principal,
    # `_reponer()` no debe haber sometido NINGÚN grupo sano restante a ese
    # pool recién recreado -- el despacho termina antes de agotar los 4
    # grupos disponibles.
    assert total_grupos < 4, "no debía someter mas trabajo al pool recreado tras detener() intermedio"
    assert total_documentos < 4
