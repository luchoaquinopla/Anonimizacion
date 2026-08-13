"""Pruebas RED de contrato para la ingesta efímera de laboratorio con datos sintéticos."""

from dataclasses import fields
from importlib import import_module

PuertoEntradaIngesta = import_module(
    "ingesta_clinica.aplicacion.puertos.entrada"
).PuertoEntradaIngesta
ResultadoClasificacionFamilia = import_module(
    "ingesta_clinica.aplicacion.puertos.salida"
).ResultadoClasificacionFamilia
crear_puerto_entrada_ingesta = import_module(
    "ingesta_clinica.composicion"
).crear_puerto_entrada_ingesta
extraccion = import_module("ingesta_clinica.dominio.extraccion")
ESTADOS_EXTRACCION = extraccion.ESTADOS_EXTRACCION
ResultadoExtraccion = extraccion.ResultadoExtraccion
ResolucionCampo = extraccion.ResolucionCampo
PoliticaDecision = import_module("ingesta_clinica.dominio.politica").PoliticaDecision


ESTADOS_EXTRACCION_ESPERADOS = {
    "verificado",
    "no_presente",
    "faltante",
    "ambiguo",
    "malformado",
    "truncado",
}


def test_estados_de_extraccion_son_exhaustivos_y_resolucion_de_campo_es_explicita() -> (
    None
):
    """Cada campo del inventario disponible está representado por un único estado conocido."""
    assert set(ESTADOS_EXTRACCION) == ESTADOS_EXTRACCION_ESPERADOS

    resultado = ResultadoExtraccion(
        campos=(
            ResolucionCampo(codigo="marcador_laboratorio_alfa", estado="verificado"),
            ResolucionCampo(codigo="marcador_laboratorio_beta", estado="no_presente"),
            ResolucionCampo(codigo="marcador_laboratorio_gamma", estado="faltante"),
            ResolucionCampo(codigo="marcador_laboratorio_delta", estado="ambiguo"),
            ResolucionCampo(codigo="marcador_laboratorio_epsilon", estado="malformado"),
            ResolucionCampo(codigo="marcador_laboratorio_zeta", estado="truncado"),
        ),
        procedencia=None,
    )

    assert {resolucion.codigo for resolucion in resultado.campos} == {
        "marcador_laboratorio_alfa",
        "marcador_laboratorio_beta",
        "marcador_laboratorio_gamma",
        "marcador_laboratorio_delta",
        "marcador_laboratorio_epsilon",
        "marcador_laboratorio_zeta",
    }
    assert {
        resolucion.estado for resolucion in resultado.campos
    } == ESTADOS_EXTRACCION_ESPERADOS


def test_politica_rechaza_campos_obligatorios_que_no_pueden_verificarse() -> None:
    for estado_bloqueante in ("faltante", "ambiguo", "malformado", "truncado"):
        resultado_decision = PoliticaDecision().decidir(
            ResultadoExtraccion(
                campos=(
                    ResolucionCampo(
                        codigo="marcador_laboratorio_alfa", estado=estado_bloqueante
                    ),
                ),
                procedencia=None,
            ),
            codigos_campos_obligatorios={"marcador_laboratorio_alfa"},
            controles_privacidad_completos=True,
            informacion_identificable_residual_encontrada=False,
        )

        assert resultado_decision.aprobada is False
        assert "CAMPO_OBLIGATORIO_NO_VERIFICABLE" in resultado_decision.codigos


def test_politica_rechaza_informacion_identificable_residual_y_controles_de_privacidad_incompletos() -> (
    None
):
    resultado_decision = PoliticaDecision().decidir(
        ResultadoExtraccion(
            campos=(
                ResolucionCampo(
                    codigo="marcador_laboratorio_alfa", estado="verificado"
                ),
            ),
            procedencia=None,
        ),
        codigos_campos_obligatorios={"marcador_laboratorio_alfa"},
        controles_privacidad_completos=False,
        informacion_identificable_residual_encontrada=True,
    )

    assert resultado_decision.aprobada is False
    assert {
        "INFORMACION_IDENTIFICABLE_RESIDUAL",
        "CONTROLES_DE_PRIVACIDAD_INCOMPLETOS",
    } <= set(resultado_decision.codigos)


def test_composicion_de_ingesta_retorna_solo_una_decision_tecnica_segura() -> None:
    resultado = crear_puerto_entrada_ingesta().ingerir(b"entrada_laboratorio_sintetica")

    assert resultado.aprobada in {True, False}
    assert set(resultado.codigos)
    assert {campo.name for campo in fields(resultado)} == {
        "aprobada",
        "codigos",
        "conteos",
    }


def test_puerto_de_ingesta_acepta_un_clasificador_inyectado() -> None:
    class ClasificadorNoLaboratorio:
        def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
            return ResultadoClasificacionFamilia(
                es_laboratorio=False,
                codigo_rechazo="FAMILIA_DOCUMENTO_NO_COMPATIBLE",
                procedencia=None,
                extraccion=None,
            )

    resultado = PuertoEntradaIngesta(ClasificadorNoLaboratorio()).ingerir(b"sintetico")

    assert resultado.aprobada is False
    assert resultado.codigos == ("FAMILIA_DOCUMENTO_NO_COMPATIBLE",)
