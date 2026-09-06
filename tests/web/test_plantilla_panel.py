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
        # Las traducciones de estos tres códigos se verifican explícitamente
        # en `test_los_motivos_del_embudo_se_traducen_a_texto_llano`.
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


def test_un_corrida_id_con_cierre_de_script_no_rompe_el_script_real() -> None:
    """Hallazgo de seguridad: `json.dumps` no escapa `</`, así que un valor con
    `</script>` cerraría la etiqueta real en medio del literal. Hoy
    `corrida_id` siempre es un `uuid4()` y la ruta rechaza `/` antes de
    llegar acá -- pero la plantilla tiene que defenderse sola, no depender de
    ese filtro externo.
    """
    pagina = renderizar_panel(_payload(corrida_id="</script><script>alert(1)</script>"))

    assert "</script><script>alert(1)</script>" not in pagina
    assert "<\\/script>" in pagina
    # Sigue habiendo exactamente un `<script>` real de refresco.
    assert pagina.count("<script>\n(function () {") == 1


def test_un_corrida_id_con_comentario_html_no_rompe_el_script_real() -> None:
    """Segundo hallazgo de seguridad sobre el mismo escape: `</` no alcanza.
    Dentro de un elemento `<script>`, `<!--` sin su `-->` de cierre pone al
    tokenizador de HTML5 en el estado "script data escaped", y el
    `</script>` REAL de esta plantilla deja de interpretarse como cierre --
    el resto del documento pasa a tratarse como texto de script.
    """
    pagina = renderizar_panel(_payload(corrida_id="<!--<script>alert(1)</script>"))

    assert "<!--<script>alert(1)</script>" not in pagina
    assert "<\\!--" in pagina
    # El </script> real de refresco sigue siendo el cierre de la página.
    assert pagina.rstrip().endswith("</html>")


def test_el_estado_de_la_corrida_se_traduce_a_texto_llano() -> None:
    """No jerga interna en la primera línea que lee el operador."""
    pagina = renderizar_panel(_payload(estado="completada_con_cuarentena"))

    assert "Completada, con cuarentena" in pagina
    assert ">completada_con_cuarentena<" not in pagina


def test_un_estado_de_corrida_desconocido_se_muestra_crudo_como_ultimo_recurso() -> None:
    """Perder el dato es peor que mostrarlo feo (mismo criterio que
    `AccionRequerida.SIN_CLASIFICAR` en `reporte_cuarentena.py`)."""
    pagina = renderizar_panel(_payload(estado="un-estado-que-no-existe-todavia"))

    assert "un-estado-que-no-existe-todavia" in pagina


def test_los_motivos_del_embudo_se_traducen_a_texto_llano_y_reusan_la_tabla_de_cuarentena() -> None:
    """La columna "Motivos" no puede mostrar el código crudo cuando existe
    traducción: `reporte_cuarentena.py` ya la tiene escrita, y esta pantalla
    reusa la MISMA tabla (`codigos_cuarentena.EXPLICACION_POR_CODIGO`), no
    una copia.
    """
    from anonimizacion.web.codigos_cuarentena import EXPLICACION_POR_CODIGO
    from anonimizacion.web.reporte_cuarentena import _EXPLICACION_POR_CODIGO as tabla_del_reporte

    assert EXPLICACION_POR_CODIGO is tabla_del_reporte  # misma tabla, no una copia

    pagina = renderizar_panel(_payload())
    cuerpo, _, _script = pagina.partition("<script>")

    assert EXPLICACION_POR_CODIGO["episodio_incompleto"] in cuerpo
    assert EXPLICACION_POR_CODIGO["error_transitorio_agotado"] in cuerpo
    assert EXPLICACION_POR_CODIGO["artefacto_sobretamano"] in cuerpo
    # El código crudo NO aparece en el cuerpo visible -- sí puede aparecer
    # dentro del `<script>`, que embebe la tabla completa para que el
    # refresco también traduzca (ver `etiquetasCodigo` en `_script_polling`).
    assert "episodio_incompleto" not in cuerpo
    assert "error_transitorio_agotado" not in cuerpo


def test_un_codigo_de_motivo_sin_traduccion_se_muestra_crudo_como_ultimo_recurso() -> None:
    pagina = renderizar_panel(
        _payload(
            etapas=[
                {
                    "etapa": "salida",
                    "llegaron": 10,
                    "apartados": 1,
                    "codigos": {"codigo-que-todavia-no-esta-en-la-tabla": 1},
                }
            ]
        )
    )

    assert "codigo-que-todavia-no-esta-en-la-tabla" in pagina


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


def test_un_residuo_negativo_dibuja_la_ficha_de_descuadre_visible() -> None:
    """10.5: un embudo con residuo negativo se dibuja con su propia ficha, nunca un cero."""
    pagina = renderizar_panel(_payload(residuo=-3, cierra=False, marcha="descuadre"))

    assert 'id="ficha-descuadre">' in pagina  # visible: sin `style="display: none"`
    assert "Descuadre: 3 documentos con más de un desenlace" in pagina
    assert "reprocesamiento duplicado" in pagina
    # La ficha "En proceso" es la que no aplica acá, y queda oculta.
    assert 'id="ficha-en-proceso" style="display: none">' in pagina


def test_un_residuo_no_negativo_muestra_en_proceso_y_oculta_el_descuadre() -> None:
    """10.6 (decisión de apply): "En proceso" y "Descuadre" son mutuamente
    excluyentes según `cierra`. La que no aplica queda OCULTA con CSS
    (`display: none`), no omitida del marcado -- ambas viven siempre en el
    DOM para que el `<script>` pueda alternar su visibilidad con un cambio de
    `style` y `textContent`, sin depender de `innerHTML` para crear nodos
    nuevos si un refresco posterior cambia de estado. No hay dato sensible en
    juego: son conteos administrativos ya derivados de tablas sin PII.
    """
    pagina = renderizar_panel(_payload(residuo=10, cierra=True, marcha="en_vuelo"))

    assert 'id="ficha-en-proceso">' in pagina  # visible: sin `style="display: none"`
    assert 'id="valor-residuo">10' in pagina
    assert 'id="ficha-descuadre" style="display: none">' in pagina


def test_la_ficha_residuo_se_llama_en_proceso_no_por_el_nombre_del_campo() -> None:
    """El nombre técnico (`residuo`) vive en el JSON, no en la pantalla --
    mismo criterio que `reporte_cuarentena.py` aplicó a los códigos internos.
    """
    pagina = renderizar_panel(_payload(residuo=10, cierra=True))

    assert "En proceso" in pagina
    assert ">Residuo<" not in pagina


def test_la_ficha_apartados_explica_que_requieren_revision() -> None:
    pagina = renderizar_panel(_payload())

    assert "Requieren revisión" in pagina
    assert 'href="/cuarentena"' in pagina


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


def test_la_barra_mide_la_perdida_relativa_a_la_peor_etapa() -> None:
    """La barra tiene que variar entre etapas -- si midiera `llegaron/entraron`
    a mitad de corrida, las siete darían ~el mismo ancho y no comunicarían
    nada. Acá "coordinacion" tiene 10x más apartados que "salida": su barra
    tiene que ser la más larga, y "salida" una fracción chica de esa barra.
    """
    pagina = renderizar_panel(
        _payload(
            etapas=[
                {"etapa": "ingesta", "llegaron": 100, "apartados": 0, "codigos": {}},
                {"etapa": "extraccion", "llegaron": 100, "apartados": 0, "codigos": {}},
                {"etapa": "parseo", "llegaron": 100, "apartados": 0, "codigos": {}},
                {"etapa": "reconciliacion", "llegaron": 100, "apartados": 0, "codigos": {}},
                {"etapa": "coordinacion", "llegaron": 100, "apartados": 20, "codigos": {"episodio_incompleto": 20}},
                {"etapa": "pseudonimizacion", "llegaron": 80, "apartados": 0, "codigos": {}},
                {"etapa": "salida", "llegaron": 80, "apartados": 2, "codigos": {"error_transitorio_agotado": 2}},
            ]
        )
    )

    assert 'id="etapa-coordinacion-barra" style="width: 100.0%"' in pagina
    assert 'id="etapa-salida-barra" style="width: 10.0%"' in pagina
    assert 'id="etapa-ingesta-barra" style="width: 0.0%"' in pagina


def test_no_hay_codigo_muerto_en_el_js() -> None:
    """`etiquetasEtapa` se definía y nunca se usaba -- una pista falsa para
    quien mantenga esta pantalla."""
    pagina = renderizar_panel(_payload())

    assert "etiquetasEtapa" not in pagina


def test_el_throughput_se_oculta_cuando_la_estimacion_es_descuadre() -> None:
    """No puede convivir "no se puede estimar" con dos números de throughput
    al lado -- contradice el mensaje."""
    pagina = renderizar_panel(_payload(estimacion={"situacion": "descuadre"}))

    assert 'id="linea-throughput" style="display: none"' in pagina


def test_el_throughput_se_muestra_cuando_hay_estimacion_disponible() -> None:
    pagina = renderizar_panel(_payload())

    assert 'id="linea-throughput">' in pagina  # visible: sin `style="display: none"`
    assert "500.0" in pagina
