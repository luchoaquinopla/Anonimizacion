"""Pruebas de triangulación para resolver campos sin retener valores clínicos."""

from importlib import import_module

extraccion = import_module("ingesta_clinica.dominio.extraccion")
CandidatoCampo = extraccion.CandidatoCampo
PoliticaResolucionCampo = extraccion.PoliticaResolucionCampo
ResolucionCampo = extraccion.ResolucionCampo
ResultadoExtraccion = extraccion.ResultadoExtraccion
PoliticaDecision = import_module("ingesta_clinica.dominio.politica").PoliticaDecision


def test_unidad_incompatible_se_resuelve_como_malformada_sin_retener_valor() -> None:
    resolucion = PoliticaResolucionCampo().resolver(
        codigo="marcador_laboratorio_alfa",
        candidatos=(CandidatoCampo(unidad_compatible=False),),
    )

    assert resolucion == ResolucionCampo(
        codigo="marcador_laboratorio_alfa", estado="malformado"
    )
    assert "valor" not in repr(resolucion).lower()


def test_valor_malformado_se_resuelve_sin_conservarlo() -> None:
    resolucion = PoliticaResolucionCampo().resolver(
        codigo="marcador_laboratorio_alfa",
        candidatos=(CandidatoCampo(valor_malformado=True),),
    )

    assert resolucion.estado == "malformado"
    assert set(resolucion.__dict__) == {"codigo", "estado"}


def test_valor_truncado_se_resuelve_sin_conservarlo() -> None:
    resolucion = PoliticaResolucionCampo().resolver(
        codigo="marcador_laboratorio_alfa",
        candidatos=(CandidatoCampo(valor_truncado=True),),
    )

    assert resolucion.estado == "truncado"
    assert set(resolucion.__dict__) == {"codigo", "estado"}


def test_candidatos_multiples_se_resuelven_como_ambiguos() -> None:
    resolucion = PoliticaResolucionCampo().resolver(
        codigo="marcador_laboratorio_alfa",
        candidatos=(CandidatoCampo(), CandidatoCampo()),
    )

    assert resolucion.estado == "ambiguo"


def test_ausencia_legitima_de_campo_opcional_no_bloquea_la_decision() -> None:
    resolucion = PoliticaResolucionCampo().resolver(
        codigo="marcador_laboratorio_opcional", candidatos=()
    )
    resultado_decision = PoliticaDecision().decidir(
        ResultadoExtraccion(
            campos=(resolucion,),
            procedencia=None,
            codigos_campos_inventario={"marcador_laboratorio_opcional"},
        ),
        codigos_campos_obligatorios=frozenset(),
        controles_privacidad_completos=True,
        informacion_identificable_residual_encontrada=False,
    )

    assert resolucion.estado == "no_presente"
    assert resultado_decision.aprobada is True


def test_resultado_exige_estado_conocido_para_cada_campo_del_inventario() -> None:
    try:
        ResultadoExtraccion(
            campos=(
                ResolucionCampo(
                    codigo="marcador_laboratorio_alfa", estado="verificado"
                ),
            ),
            procedencia=None,
            codigos_campos_inventario={
                "marcador_laboratorio_alfa",
                "marcador_laboratorio_beta",
            },
        )
    except ValueError as error:
        assert "inventario" in str(error)
    else:
        raise AssertionError("Se aceptó un campo del inventario sin estado explícito.")

    resultado = ResultadoExtraccion(
        campos=(
            ResolucionCampo(codigo="marcador_laboratorio_alfa", estado="verificado"),
            ResolucionCampo(codigo="marcador_laboratorio_beta", estado="no_presente"),
        ),
        procedencia=None,
        codigos_campos_inventario={
            "marcador_laboratorio_alfa",
            "marcador_laboratorio_beta",
        },
    )

    assert {resolucion.codigo for resolucion in resultado.campos} == set(
        resultado.codigos_campos_inventario
    )
