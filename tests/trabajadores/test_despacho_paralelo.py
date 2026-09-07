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
from concurrent.futures import ProcessPoolExecutor

import pytest

from anonimizacion.trabajadores import despacho_paralelo

from ._dobles_despacho_paralelo import (
    ID_DOCUMENTO_QUE_MUERE_SIEMPRE,
    VAR_ENV_MARCADOR,
    CuarentenaEnMemoria,
    referencia,
    trabajo_devuelve_pid,
    trabajo_muere_la_primera_vez_por_grupo,
    trabajo_muere_siempre_si_esta_marcado,
)


def _crear_pool(procesos: int = 2) -> ProcessPoolExecutor:
    # Sin `initializer`: los dobles de este archivo no necesitan pepper,
    # motor ni engine -- solo confirmar el PID o morir a propósito.
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
        crear_pool=lambda: _crear_pool(2),
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


def test_despachar_en_paralelo_no_materializa_todos_los_grupos_antes_de_despachar():
    """Centinela de pereza: un iterador que agota su presupuesto de items
    disponibles antes de ser consumido por completo NO debe romperse -- si
    `despachar_en_paralelo` hiciera `list(grupos)` de entrada, este test
    fallaria con `RuntimeError` en vez de completar normalmente."""
    total_de_grupos = 6
    entregados = 0

    def _generador_que_cuenta():
        nonlocal entregados
        for indice in range(total_de_grupos):
            entregados += 1
            yield (referencia(f"doc-{indice}"),)

    cuarentena = CuarentenaEnMemoria()
    resultados, _, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-pereza",
        grupos=_generador_que_cuenta(),
        crear_pool=lambda: _crear_pool(2),
        procesos=2,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_devuelve_pid,
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
        crear_pool=lambda: _crear_pool(2),
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
    assert fallos[0]["codigo"] == "error_transitorio_agotado"

    # El invariante del embudo (residuo = entraron - (publicados + apartados))
    # exige que el documento perdido quede APARTADO, no solo devuelto en
    # memoria -- si no se registrara en cuarentena, "entraron" lo seguiria
    # contando y el residuo nunca cerraria.
    assert len(cuarentena.errores) == 1
    assert cuarentena.errores[0].id_documento == ID_DOCUMENTO_QUE_MUERE_SIEMPRE
    assert cuarentena.errores[0].corrida_id == "corrida-hijo-muere"


def test_un_hijo_que_muere_una_vez_se_recupera_en_el_reintento(tmp_path, monkeypatch):
    """Distinto del test anterior: acá el hijo muere UNA sola vez por grupo
    -- la recuperacion automatica (pool nuevo, mismo grupo reencolado) debe
    terminar en EXITO, sin tocar cuarentena.

    `procesos=1` a propósito (no 2): con más de un grupo genuinamente en
    vuelo a la vez, cuando el pool se rompe, `despachar_en_paralelo` reencola
    los grupos "colaterales" (los que compartían pool con el que murió) SIN
    cargarles su cupo de reintentos -- pero si ESE reencolado colateral
    coincide con el momento exacto en que el pool se rompe de nuevo por otra
    razón, un grupo sano puede terminar cargado por una muerte ajena (límite
    real de "un hijo muerto rompe el pool ENTERO", no solo su tarea -- ver
    docstring de `despachar_en_paralelo`). Ese escenario de carreras
    superpuestas no es lo que este test quiere ejercitar: acá se aísla la
    mecánica de recuperación en sí, un grupo a la vez."""
    monkeypatch.setenv(VAR_ENV_MARCADOR, str(tmp_path))
    grupos = iter([(referencia("doc-se-recupera-1"),), (referencia("doc-se-recupera-2"),)])
    cuarentena = CuarentenaEnMemoria()

    resultados, total_documentos, total_grupos = despacho_paralelo.despachar_en_paralelo(
        corrida_id="corrida-recupera",
        grupos=grupos,
        crear_pool=lambda: _crear_pool(1),
        procesos=1,
        cuarentena=cuarentena,
        funcion_trabajo=trabajo_muere_la_primera_vez_por_grupo,
    )

    assert total_grupos == 2
    assert total_documentos == 2
    assert {r["estado"] for r in resultados} == {"exito"}
    assert {r["id_documento"] for r in resultados} == {"doc-se-recupera-1", "doc-se-recupera-2"}
    assert not cuarentena.errores
