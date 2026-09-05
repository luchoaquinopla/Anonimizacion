"""La pantalla del panel: polling en línea, escape, y la ficha de descuadre.

Precedente obligatorio: `plantilla_reporte.py`/`test_plantilla_reporte.py`.
La diferencia central es que ACÁ el `<script>` es un requisito (10.1), no un
accidente que haya que evitar: el panel refresca solo, sin depender de que
el operador recargue la página cada vez para ver el avance de una corrida
que puede durar horas.

**No se copia** la aserción `"<script" not in pagina` de
`tests/web/test_plantilla_reporte.py:59-71` -- esa pertenece al reporte de
cuarentena, que no lleva script. Acá el requisito es el inverso.
"""

from __future__ import annotations

from typing import Any

from anonimizacion.web.plantilla_panel import renderizar_panel


def _payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "corrida_id": "corrida-1",
        "estado": "procesando",
        "generado_en": "2026-09-05T13:00:00+00:00",
        "entraron": 100,
        "publicados": 60,
        "apartados": 30,
        "residuo": 10,
        "cierra": True,
        "marcha": "en_vuelo",
        "etapas": [
            {"etapa": "ingesta", "llegaron": 100, "apartados": 2, "codigos": {"artefacto_sobretamano": 2}},
            {"etapa": "extraccion", "llegaron": 98, "apartados": 0, "codigos": {}},
            {"etapa": "parseo", "llegaron": 98, "apartados": 0, "codigos": {}},
            {"etapa": "reconciliacion", "llegaron": 98, "apartados": 0, "codigos": {}},
            {"etapa": "coordinacion", "llegaron": 98, "apartados": 5, "codigos": {"episodio_incompleto": 5}},
            {"etapa": "pseudonimizacion", "llegaron": 93, "apartados": 0, "codigos": {}},
            {"etapa": "salida", "llegaron": 93, "apartados": 23, "codigos": {"error_transitorio_agotado": 23}},
        ],
        "throughput_por_hora": {"optimista": 500.0, "pesimista": 420.5},
        "estimacion": {"situacion": "disponible", "restante_seg_min": 1200, "restante_seg_max": 1800},
    }
    base.update(over)
    return base


def test_el_polling_va_en_linea_y_la_pagina_no_referencia_la_red() -> None:
    """10.1: el polling en línea es un requisito, no un accidente."""
    pagina = renderizar_panel(_payload())

    assert "http://" not in pagina
    assert "https://" not in pagina
    assert "<script src" not in pagina
    assert "<script>" in pagina


def test_el_refresco_usa_textcontent_y_nunca_innerhtml() -> None:
    """10.3: literal ausencia de `innerHTML` en el JS embebido."""
    pagina = renderizar_panel(_payload())

    assert "innerHTML" not in pagina
    assert "textContent" in pagina


def test_un_codigo_de_cuarentena_con_marcado_llega_escapado() -> None:
    """10.3: un código con HTML incrustado no se interpreta en el primer pintado."""
    pagina = renderizar_panel(
        _payload(
            etapas=[
                {
                    "etapa": "salida",
                    "llegaron": 10,
                    "apartados": 1,
                    "codigos": {"<img src=x onerror=alert(1)>": 1},
                }
            ]
        )
    )

    assert "<img src=x" not in pagina
    assert "&lt;img" in pagina


def test_un_residuo_negativo_dibuja_la_ficha_de_descuadre() -> None:
    """10.5: un embudo con residuo negativo se dibuja con su propia ficha, nunca un cero."""
    pagina = renderizar_panel(_payload(residuo=-3, cierra=False, marcha="descuadre"))

    assert 'id="ficha-descuadre"' in pagina
    assert "Descuadre: 3 documentos con más de un desenlace" in pagina
    assert "reprocesamiento duplicado" in pagina


def test_un_residuo_no_negativo_no_deja_rastro_del_texto_de_descuadre() -> None:
    """10.6: sin descuadre real, la ficha queda vacía y oculta en el cuerpo servido.

    El texto "Descuadre: ..." SÍ aparece dentro del `<script>` (la plantilla
    de refresco que el JS usaría si un fetch posterior encontrara
    `cierra: false`) -- lo que no puede aparecer es el marcado VISIBLE de la
    ficha en el cuerpo de la página servida.
    """
    pagina = renderizar_panel(_payload(residuo=10, cierra=True, marcha="en_vuelo"))
    cuerpo, _, _script = pagina.partition("<script>")

    assert "Descuadre:" not in cuerpo
    assert 'id="ficha-descuadre" style="display: none">' in cuerpo


def test_el_primer_pintado_ya_trae_los_numeros() -> None:
    """10.8: la página es útil antes de que corra un solo `fetch`."""
    pagina = renderizar_panel(_payload(entraron=100, publicados=60, apartados=30))

    assert 'id="valor-entraron">100' in pagina
    assert 'id="valor-publicados">60' in pagina
    assert 'id="valor-apartados">30' in pagina


def test_las_siete_etapas_se_dibujan_en_orden() -> None:
    """Requisito 2 de la spec: siete etapas, ni detección ni detección de PII."""
    pagina = renderizar_panel(_payload())

    assert pagina.index("Ingesta") < pagina.index("Extracción") < pagina.index("Parseo")
    assert "Detección" not in pagina
