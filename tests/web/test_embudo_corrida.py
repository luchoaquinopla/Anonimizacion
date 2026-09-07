"""Tests del modelo de lectura del embudo (tasks.md, Fase 8).

Las pruebas de aritmética (8.1, 8.3, 8.5, 8.7, 8.13) ejercitan
`calcular_embudo`, la función PURA que no toca la base -- así se puede fijar
cada borde con una serie de agregados sintética, sin pagar el costo de un
motor real. Las de integración (8.9, 8.11) sí montan un motor real y viven en
`tests/integracion/`, porque necesitan probar algo que sólo existe contra
filas de verdad: que el embudo no lee `documento_corrida.estado`, y que el
solapamiento se detecta por el camino real de reintentos agotados.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from anonimizacion.web.embudo_corrida import (
    ETAPAS_EMBUDO,
    Embudo,
    Estimacion,
    PerdidaEtapa,
    calcular_embudo,
)

_AHORA = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def test_las_ocho_etapas_se_exponen_en_el_orden_de_ejecucion() -> None:
    # 8.1: el orden de ejecución real (design.md, Decisión 8) intercala
    # `coordinacion` DESPUÉS de `pseudonimizacion`, no entre `reconciliacion`
    # y `deteccion_pii` como lo declara el enum `Etapa` -- si `calcular_embudo`
    # se limitara a iterar ese enum, este test lo detectaría.
    #
    # `despacho` (openspec `paralelismo-de-procesamiento` PR 3, revisión
    # adversarial): va justo después de `ingesta`, antes de `extraccion` --
    # un documento apartado ahí nunca llegó a ejecutarse en el pipeline.
    perdidas = {
        "salida": {"error_transitorio_agotado": 1},
        "ingesta": {"artefacto_sobretamano": 1},
        "despacho": {"proceso_interrumpido": 1},
        "coordinacion": {"episodio_incompleto": 1},
    }

    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=10,
        publicados=5,
        perdidas=perdidas,
        terminados_en_ventana=0,
        primero=None,
        ultimo=None,
        ahora=_AHORA,
    )

    assert [e.etapa for e in embudo.etapas] == list(ETAPAS_EMBUDO)
    assert list(ETAPAS_EMBUDO) == [
        "ingesta",
        "despacho",
        "extraccion",
        "parseo",
        "reconciliacion",
        "coordinacion",
        "pseudonimizacion",
        "salida",
    ]
    # Centinela del bug real (revisión adversarial): antes de agregar
    # `despacho` a `ETAPAS_EMBUDO`, un apartado con esa etapa se sumaba al
    # total global pero el `for etapa in ETAPAS_EMBUDO` lo saltaba sin
    # restarlo de `llegaron` en ningún punto -- el desglose por etapa
    # quedaba inflado desde ahí en adelante. Con la etapa ya en el
    # vocabulario: `llegaron` arranca en `con_desenlace` (9, publicados +
    # apartados), `ingesta` resta su propio apartado (9 -> 8 para la
    # siguiente etapa), `despacho` ve `llegaron=8` y resta el suyo
    # (8 -> 7 para `extraccion`) -- si `despacho` no estuviera en el
    # vocabulario, ese apartado nunca se restaría y `extraccion` vería 8,
    # no 7.
    por_etapa = {e.etapa: e for e in embudo.etapas}
    assert por_etapa["ingesta"].llegaron == 9
    assert por_etapa["despacho"].llegaron == 8
    assert por_etapa["despacho"].apartados == 1
    assert por_etapa["extraccion"].llegaron == 7
    # El ultimo `llegaron` restante (via `pseudonimizacion`/`salida`) tiene
    # que converger exactamente a `publicados` -- es la propiedad que
    # confirma que TODOS los apartados fueron restados en algun punto.
    assert por_etapa["salida"].llegaron - por_etapa["salida"].apartados == 5


def test_el_residuo_negativo_no_se_recorta_a_cero() -> None:
    # 8.3: el centinela de solapamiento, parte aritmética. Un embudo con más
    # apartados que inventariados tiene que dar un residuo NEGATIVO, nunca
    # cero -- si en algún punto del cálculo hubiera un `max(0, ...)`, este
    # test no podría distinguirlo de un embudo que simplemente cerró en cero.
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=3,
        publicados=2,
        perdidas={"salida": {"error_transitorio_agotado": 3}},
        terminados_en_ventana=0,
        primero=None,
        ultimo=None,
        ahora=_AHORA,
    )

    assert embudo.residuo == 3 - (2 + 3)
    assert embudo.residuo == -2
    assert embudo.cierra is False


def test_el_residuo_cero_cierra() -> None:
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=5,
        publicados=3,
        perdidas={"salida": {"error_transitorio_agotado": 2}},
        terminados_en_ventana=0,
        primero=None,
        ultimo=None,
        ahora=_AHORA,
    )

    assert embudo.residuo == 0
    assert embudo.cierra is True


def test_el_sobretamano_cuenta_en_ingesta_pero_no_en_throughput() -> None:
    # 8.5: un documento apartado por `artefacto_sobretamano` nunca se leyó
    # (design.md, Requisito 4) -- pesa en la barra de ingesta, no en el
    # denominador de throughput.
    primero = _AHORA - timedelta(minutes=10)
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=300,
        publicados=250,
        perdidas={"ingesta": {"artefacto_sobretamano": 50}},
        terminados_en_ventana=10,
        primero=primero,
        ultimo=_AHORA,
        ahora=_AHORA,
    )

    etapa_ingesta = embudo.etapas[0]
    assert etapa_ingesta.etapa == "ingesta"
    assert etapa_ingesta.apartados == 50
    # terminados = publicados + apartados - apartados_sobretamano = 250+50-50 = 250
    # restante = entraron - terminados = 300 - 250 = 50 -> por debajo del minimo
    # de 200 no aplica acá porque terminados=250 >= 200, así que se estima.
    assert embudo.estimacion.situacion == "disponible"
    # Si el sobretamaño contara como throughput, la tasa pesimista sería sobre
    # terminados=300 en vez de 250 -- distinto denominador, distinto resultado.
    tasa_pesimista_incluyendo_sobretamano = 300 / (600)
    tasa_pesimista_excluyendo_sobretamano = 250 / (600)
    assert embudo.throughput_por_hora["pesimista"] != round(
        tasa_pesimista_incluyendo_sobretamano * 3600, 2
    )
    assert embudo.throughput_por_hora["pesimista"] == round(
        tasa_pesimista_excluyendo_sobretamano * 3600, 2
    )


def test_borde_entraron_cero_da_midiendo() -> None:
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=0,
        publicados=0,
        perdidas={},
        terminados_en_ventana=0,
        primero=None,
        ultimo=None,
        ahora=_AHORA,
    )

    assert embudo.estimacion == Estimacion(situacion="midiendo")
    assert embudo.throughput_por_hora == {"optimista": 0.0, "pesimista": 0.0}
    assert embudo.residuo == 0
    assert embudo.cierra is True


def test_borde_menos_de_200_terminados_da_midiendo() -> None:
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=1000,
        publicados=199,
        perdidas={},
        terminados_en_ventana=5,
        primero=_AHORA - timedelta(minutes=1),
        ultimo=_AHORA,
        ahora=_AHORA,
    )

    assert embudo.estimacion.situacion == "midiendo"


def test_borde_ventana_reciente_vacia_da_sin_avance() -> None:
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=1000,
        publicados=300,
        perdidas={},
        terminados_en_ventana=0,  # nadie termino en los ultimos 5 minutos
        primero=_AHORA - timedelta(hours=2),
        ultimo=_AHORA - timedelta(minutes=30),
        ahora=_AHORA,
    )

    assert embudo.estimacion.situacion == "sin_avance"
    assert embudo.marcha == "sin_avance"


def test_borde_restante_cero_da_todos_con_desenlace() -> None:
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=300,
        publicados=300,
        perdidas={},
        terminados_en_ventana=10,
        primero=_AHORA - timedelta(hours=1),
        ultimo=_AHORA,
        ahora=_AHORA,
    )

    assert embudo.estimacion.situacion == "disponible"
    assert embudo.estimacion.restante_seg_min == 0
    assert embudo.estimacion.restante_seg_max == 0
    assert embudo.marcha == "completa"


def test_borde_restante_negativo_da_descuadre() -> None:
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=100,
        publicados=250,
        perdidas={},
        terminados_en_ventana=10,
        primero=_AHORA - timedelta(hours=1),
        ultimo=_AHORA,
        ahora=_AHORA,
    )

    assert embudo.estimacion.situacion == "descuadre"
    assert embudo.marcha == "descuadre"
    assert embudo.residuo == 100 - 250
    assert embudo.cierra is False


def test_caso_disponible_da_rango_con_dos_cotas() -> None:
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=1000,
        publicados=300,
        perdidas={},
        terminados_en_ventana=60,  # 60 en 5 min -> 720/hora
        primero=_AHORA - timedelta(hours=1),  # 300 en 1h -> 300/hora
        ultimo=_AHORA,
        ahora=_AHORA,
        )

    assert embudo.estimacion.situacion == "disponible"
    assert embudo.estimacion.restante_seg_min is not None
    assert embudo.estimacion.restante_seg_max is not None
    assert embudo.throughput_por_hora["optimista"] == 720.0
    assert embudo.throughput_por_hora["pesimista"] == 300.0


def test_corrida_sin_ningun_documento_todo_en_cero() -> None:
    # Requisito 5: corrida recien creada.
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=0,
        publicados=0,
        perdidas={},
        terminados_en_ventana=0,
        primero=None,
        ultimo=None,
        ahora=_AHORA,
    )

    assert embudo.publicados == 0
    assert embudo.apartados == 0
    assert all(e.llegaron == 0 and e.apartados == 0 for e in embudo.etapas)
    assert embudo.estimacion.situacion == "midiendo"


def test_corrida_completa_sin_fallos_de_infraestructura_cierra_en_cero() -> None:
    # 8.13: cierra la invariante en el lado positivo -- sin ningun fallo de
    # infraestructura, publicados + apartados == entraron exactamente.
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=50,
        publicados=45,
        perdidas={"parseo": {"parseo_incompleto": 5}},
        terminados_en_ventana=0,
        primero=_AHORA - timedelta(hours=1),
        ultimo=_AHORA,
        ahora=_AHORA,
    )

    assert embudo.residuo == 0
    assert embudo.cierra is True


def test_etapas_no_declaradas_no_participan_del_embudo() -> None:
    # Requisito 2: deteccion y deteccion_pii no producen cuarentena -- si
    # llegaran en `perdidas` (no deberían, pero el modelo de lectura no debe
    # asumirlo), no tienen que aparecer como barra propia.
    embudo = calcular_embudo(
        corrida_id="c1",
        entraron=10,
        publicados=8,
        perdidas={"deteccion": {"algo": 2}},
        terminados_en_ventana=0,
        primero=None,
        ultimo=None,
        ahora=_AHORA,
    )

    assert "deteccion" not in [e.etapa for e in embudo.etapas]
    assert len(embudo.etapas) == len(ETAPAS_EMBUDO)


def test_los_dataclasses_de_salida_no_tienen_campos_llamados_como_columnas_de_pii() -> None:
    """Chequeo débil y deliberadamente acotado: sólo mira los NOMBRES de los
    campos de los dataclasses de salida, nunca el SQL que arma
    `construir_embudo`. No protegería contra un futuro `select(Cuarentena)`
    completo que trajera esas columnas al proceso aunque después no las
    expusiera acá -- eso lo cubre
    `test_las_consultas_reales_nunca_proyectan_columnas_de_pii`, en
    `tests/integracion/test_embudo_corrida_integracion.py`, que inspecciona
    el SQL compilado de verdad.
    """
    campos_embudo = set(Embudo.__dataclass_fields__)
    campos_perdida = set(PerdidaEtapa.__dataclass_fields__)
    assert "ruta_autorizada" not in campos_embudo | campos_perdida
    assert "huella_contenido" not in campos_embudo | campos_perdida


def test_la_cache_purga_entradas_vencidas_y_no_crece_sin_limite() -> None:
    """La memoización de 1s (design.md, "Plan de acceso") no dice nada de
    purgar -- si nada la limpia, cada `corrida_id` alguna vez consultado deja
    una entrada muerta para siempre en un plano de control que corre meses
    sin reiniciarse. `construir_embudo` recibe un reloj inyectable (mismo
    patrón que `dormir` en `pipeline/ejecutor.py`) para poder simular el paso
    del tiempo sin dormir de verdad.
    """
    from anonimizacion.web import embudo_corrida

    embudo_corrida._CACHE.clear()
    motor = _motor_vacio_para_pruebas_de_cache()

    reloj = {"t": 0.0}

    for i in range(50):
        # Cada consulta separada por 10s: muy por encima del TTL de 1s, así
        # que ninguna corrida previa debería sobrevivir a la siguiente lectura.
        reloj["t"] = i * 10.0
        embudo_corrida.construir_embudo(motor, f"corrida-{i}", reloj=lambda: reloj["t"])

    assert len(embudo_corrida._CACHE) < 50, (
        "la cache crecio sin limite: cada corrida_id alguna vez consultado "
        "dejo una entrada que nadie purgo"
    )
    assert len(embudo_corrida._CACHE) == 1  # solo la ultima, todavia fresca


def _motor_vacio_para_pruebas_de_cache():
    import sqlalchemy as sa

    from anonimizacion.salida.modelos_orm import Base

    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor
