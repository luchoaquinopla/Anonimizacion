"""Caracterización de la salida del reporte de corrida (Entrega 0, Requisito 5).

Fija el texto exacto que `anonimizacion.comandos.procesar::_despachar_grupos`
(el camino `procesos > 1`) imprime al leer `MetricasDespacho`
(`despacho_paralelo.py:330`) -- distinto del OTRO sistema de métricas
(`observabilidad/metricas.py`), que E5 retira (`design.md`, "Cuidado" en la
propuesta). Monkeypatchea `despachar_en_paralelo` para simular
recreaciones/reprocesos conocidos sin levantar `ProcessPoolExecutor` real.

Corrección mecánica (auditoria-y-poda, E4): mismo caso que
`test_codigos_cuarentena.py` -- el módulo se movió de `scripts/` (cargado
por ruta) a `anonimizacion.comandos.procesar` (paquete real); ninguna
aserción de abajo cambia.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.caracterizacion


def _cargar_script() -> ModuleType:
    """Import normal -- ver nota de corrección mecánica arriba."""
    from anonimizacion.comandos import procesar as modulo

    return modulo


def test_reporte_de_recuperacion_con_resultados_mixtos(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Escenario "reporte con resultados mixtos": éxitos, fallos y reintentos conocidos."""
    modulo = _cargar_script()
    resultados_esperados = [
        {"id_documento": "a" * 64, "estado": "exito", "tipo_documento": "laboratorio"},
        {"id_documento": "b" * 64, "estado": "error", "codigo": "episodio_incompleto", "etapa": "coordinacion"},
    ]

    def _despachar_en_paralelo_falso(*, corrida_id, grupos, crear_pool, procesos, cuarentena, metricas=None, **_kwargs):
        # Simula 3 recreaciones del pool y 5 reprocesos en aislamiento -- el
        # mismo contador que un crash real de `ProcessPoolExecutor` dejaría.
        metricas.recreaciones_de_pool_principal = 3
        metricas.reprocesos_en_aislamiento = 5
        return resultados_esperados, 2, 1

    monkeypatch.setattr(modulo.despacho_paralelo, "despachar_en_paralelo", _despachar_en_paralelo_falso)

    resultados, total_documentos, total_grupos = modulo._despachar_grupos(
        corrida_id="corrida-reporte",
        grupos_a_despachar=iter([]),
        procesos=2,
        entrada=tmp_path,
        db_url="postgresql+psycopg://x/y",
        tope_bytes=None,
        cuarentena=object(),
        directorio_marcador_pid=None,
    )

    assert resultados == resultados_esperados
    assert (total_documentos, total_grupos) == (2, 1)

    salida = capsys.readouterr().err
    assert (
        "Corrida corrida-reporte: recuperación ante procesos muertos -- "
        "3 recreación(es) del pool principal, 5 reproceso(s) en aislamiento "
        "(cada uno recarga el modelo de PII completo, ~875 MB medidos)."
    ) in salida


def test_sin_recreaciones_no_imprime_linea_de_recuperacion(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Contraparte necesaria del test de arriba: sin eventos de recuperación
    (`MetricasDespacho()` por defecto, todo en cero), el reporte no debe
    mencionar ninguna recreación -- si algún día imprimiera "0 recreación(es)"
    incondicionalmente, este test lo detectaría."""
    modulo = _cargar_script()

    def _despachar_en_paralelo_falso(*, corrida_id, grupos, crear_pool, procesos, cuarentena, metricas=None, **_kwargs):
        return [], 0, 0

    monkeypatch.setattr(modulo.despacho_paralelo, "despachar_en_paralelo", _despachar_en_paralelo_falso)

    modulo._despachar_grupos(
        corrida_id="corrida-sin-recuperacion",
        grupos_a_despachar=iter([]),
        procesos=2,
        entrada=tmp_path,
        db_url="postgresql+psycopg://x/y",
        tope_bytes=None,
        cuarentena=object(),
        directorio_marcador_pid=None,
    )

    salida = capsys.readouterr().err
    assert "recuperación ante procesos muertos" not in salida
