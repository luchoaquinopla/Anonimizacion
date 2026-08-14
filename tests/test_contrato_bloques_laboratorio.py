"""Pruebas RED del contrato futuro para bloques sintéticos de laboratorio."""

from importlib import import_module
from dataclasses import fields


AdaptadorFamiliaLaboratorio = import_module(
    "ingesta_clinica.adaptadores.salida.laboratorio"
).AdaptadorFamiliaLaboratorio
extraccion = import_module("ingesta_clinica.dominio.extraccion")
ResolucionCampo = extraccion.ResolucionCampo
ResultadoExtraccion = extraccion.ResultadoExtraccion


TEXTO_FUENTE_SINTETICO = "texto_fuente_sintetico_debe_descartarse"
VALOR_CLINICO_SINTETICO = "valor_clinico_sintetico_debe_descartarse"


def documento_laboratorio_sintetico() -> tuple[dict[str, object], ...]:
    return (
        {
            "tipo": "cabecera_documento",
            "familia_documental": "laboratorio",
            "seccion": "resultados",
            "numero_pagina": 2,
            "indice_bloque": 3,
            "texto_fuente": TEXTO_FUENTE_SINTETICO,
        },
        {
            "tipo": "fila_resultado_laboratorio",
            "codigo_campo": "marcador_laboratorio_alfa",
            "estado_extraido": "verificado",
            "numero_pagina": 2,
            "indice_bloque": 7,
            "valor_clinico": VALOR_CLINICO_SINTETICO,
        },
    )


def test_clasifica_laboratorio_desde_la_estructura_explicita_de_bloques() -> None:
    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(
        documento_laboratorio_sintetico()
    )

    assert resultado.es_laboratorio is True
    assert resultado.codigo_rechazo is None


def test_rechaza_estructura_no_laboratorio_aun_si_el_texto_contiene_el_marcador_actual() -> (
    None
):
    bloques_no_laboratorio = (
        {
            "tipo": "cabecera_documento",
            "familia_documental": "administrativo",
            "seccion": "resumen",
            "numero_pagina": 1,
            "indice_bloque": 0,
            "texto_fuente": "laboratorio",
        },
    )

    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(bloques_no_laboratorio)

    assert resultado.es_laboratorio is False
    assert resultado.codigo_rechazo == "FAMILIA_DOCUMENTO_NO_COMPATIBLE"
    assert resultado.procedencia is None
    assert resultado.extraccion is None


def test_procedencia_transitoria_contiene_solo_coordenadas_tecnicas_permitidas() -> (
    None
):
    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(
        documento_laboratorio_sintetico()
    )

    procedencia_esperada = {"numero_pagina": 2, "indice_bloque": 7}
    assert resultado.procedencia == procedencia_esperada
    assert resultado.extraccion is not None
    assert resultado.extraccion.procedencia == procedencia_esperada
    assert set(resultado.procedencia) == {"numero_pagina", "indice_bloque"}
    assert all(isinstance(valor, int) for valor in resultado.procedencia.values())


def test_convierte_bloques_de_laboratorio_al_contrato_existente_de_extraccion() -> None:
    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(
        documento_laboratorio_sintetico()
    )

    assert resultado.extraccion == ResultadoExtraccion(
        campos=(
            ResolucionCampo(codigo="marcador_laboratorio_alfa", estado="verificado"),
        ),
        procedencia={"numero_pagina": 2, "indice_bloque": 7},
    )


def test_resultados_publicos_e_intermedios_no_retienen_texto_ni_valor_clinico() -> None:
    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(
        documento_laboratorio_sintetico()
    )

    assert {campo.name for campo in fields(resultado)} == {
        "es_laboratorio",
        "codigo_rechazo",
        "procedencia",
        "extraccion",
    }
    assert resultado.extraccion is not None
    assert {campo.name for campo in fields(resultado.extraccion)} == {
        "campos",
        "procedencia",
        "codigos_campos_inventario",
    }
    assert all(
        {campo.name for campo in fields(resolucion)} == {"codigo", "estado"}
        for resolucion in resultado.extraccion.campos
    )
    assert TEXTO_FUENTE_SINTETICO not in repr(resultado)
    assert VALOR_CLINICO_SINTETICO not in repr(resultado)


def test_orden_variable_de_bloques_y_filas_produce_resultado_determinista() -> None:
    bloques_ordenados = (
        {
            "tipo": "cabecera_documento",
            "familia_documental": "laboratorio",
            "texto_fuente": TEXTO_FUENTE_SINTETICO,
        },
        {
            "tipo": "fila_resultado_laboratorio",
            "codigo_campo": "marcador_laboratorio_beta",
            "estado_extraido": "no_presente",
            "numero_pagina": 4,
            "indice_bloque": 9,
            "valor_clinico": VALOR_CLINICO_SINTETICO,
        },
        {
            "tipo": "fila_resultado_laboratorio",
            "codigo_campo": "marcador_laboratorio_alfa",
            "estado_extraido": "verificado",
            "numero_pagina": 2,
            "indice_bloque": 1,
            "valor_clinico": VALOR_CLINICO_SINTETICO,
        },
    )
    bloques_reordenados = (
        bloques_ordenados[1],
        bloques_ordenados[2],
        bloques_ordenados[0],
    )

    adaptador = AdaptadorFamiliaLaboratorio()
    resultado_ordenado = adaptador.extraer_bloques(bloques_ordenados)
    resultado_reordenado = adaptador.extraer_bloques(bloques_reordenados)

    esperado = ResultadoExtraccion(
        campos=(
            ResolucionCampo(codigo="marcador_laboratorio_alfa", estado="verificado"),
            ResolucionCampo(codigo="marcador_laboratorio_beta", estado="no_presente"),
        ),
        procedencia={"numero_pagina": 2, "indice_bloque": 1},
    )
    assert resultado_ordenado.extraccion == esperado
    assert resultado_reordenado.extraccion == esperado
    assert resultado_ordenado.procedencia == {"numero_pagina": 2, "indice_bloque": 1}
    assert resultado_reordenado.procedencia == {"numero_pagina": 2, "indice_bloque": 1}


def test_cabecera_de_laboratorio_sin_filas_resultado_se_rechaza_expresamente() -> None:
    bloques_incompletos = (
        {
            "tipo": "cabecera_documento",
            "familia_documental": "laboratorio",
            "numero_pagina": 3,
            "indice_bloque": 0,
            "texto_fuente": TEXTO_FUENTE_SINTETICO,
        },
    )

    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(bloques_incompletos)

    assert resultado.es_laboratorio is False
    assert resultado.codigo_rechazo == "TABLA_LABORATORIO_SIN_FILAS_RESULTADO"
    assert resultado.procedencia is None
    assert resultado.extraccion is None
    assert TEXTO_FUENTE_SINTETICO not in repr(resultado)


def test_fila_incompleta_se_rechaza_sin_retener_su_contenido() -> None:
    bloques_incompletos = (
        {
            "tipo": "cabecera_documento",
            "familia_documental": "laboratorio",
        },
        {
            "tipo": "fila_resultado_laboratorio",
            "codigo_campo": "marcador_laboratorio_alfa",
            "numero_pagina": 1,
            "indice_bloque": 2,
            "valor_clinico": VALOR_CLINICO_SINTETICO,
        },
    )

    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(bloques_incompletos)

    assert resultado.es_laboratorio is False
    assert resultado.codigo_rechazo == "FAMILIA_DOCUMENTO_NO_COMPATIBLE"
    assert resultado.procedencia is None
    assert resultado.extraccion is None
    assert VALOR_CLINICO_SINTETICO not in repr(resultado)


def test_candidatos_en_conflicto_para_un_campo_se_resuelven_como_ambiguos() -> None:
    bloques_con_conflicto = (
        {
            "tipo": "fila_resultado_laboratorio",
            "codigo_campo": "marcador_laboratorio_alfa",
            "estado_extraido": "malformado",
            "numero_pagina": 5,
            "indice_bloque": 4,
            "valor_clinico": "valor_sintetico_candidato_uno",
        },
        {
            "tipo": "cabecera_documento",
            "familia_documental": "laboratorio",
        },
        {
            "tipo": "fila_resultado_laboratorio",
            "codigo_campo": "marcador_laboratorio_alfa",
            "estado_extraido": "verificado",
            "numero_pagina": 5,
            "indice_bloque": 2,
            "valor_clinico": "valor_sintetico_candidato_dos",
        },
    )

    resultado = AdaptadorFamiliaLaboratorio().extraer_bloques(bloques_con_conflicto)

    assert resultado.es_laboratorio is True
    assert resultado.codigo_rechazo is None
    assert resultado.procedencia == {"numero_pagina": 5, "indice_bloque": 2}
    assert resultado.extraccion == ResultadoExtraccion(
        campos=(ResolucionCampo(codigo="marcador_laboratorio_alfa", estado="ambiguo"),),
        procedencia={"numero_pagina": 5, "indice_bloque": 2},
    )
    assert "valor_sintetico_candidato_uno" not in repr(resultado)
    assert "valor_sintetico_candidato_dos" not in repr(resultado)
