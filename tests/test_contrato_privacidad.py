"""Pruebas RED del límite de privacidad con valores sintéticos no identificatorios."""

from dataclasses import fields
from importlib import import_module

ValidadorPrivacidad = import_module(
    "ingesta_clinica.dominio.privacidad"
).ValidadorPrivacidad


CASOS_INFORMACION_IDENTIFICABLE_RESIDUAL = (
    ("token_identificador_sintetico", "INFORMACION_IDENTIFICABLE_RESIDUAL"),
    ("token_contacto_sintetico", "INFORMACION_IDENTIFICABLE_RESIDUAL"),
)


def test_validador_de_privacidad_bloquea_cada_hallazgo_residual_de_informacion_identificable() -> (
    None
):
    validador = ValidadorPrivacidad()

    for token_residual, codigo_esperado in CASOS_INFORMACION_IDENTIFICABLE_RESIDUAL:
        validacion = validador.validar(token_residual)

        assert validacion.aprobada is False
        assert validacion.codigo == codigo_esperado


def test_salida_tecnica_segura_expone_solo_codigos_de_decision_y_conteos() -> None:
    salida_segura = ValidadorPrivacidad().salida_segura(
        aprobada=False,
        codigos=("INFORMACION_IDENTIFICABLE_RESIDUAL",),
        conteos={"rechazados": 1},
    )

    assert {campo.name for campo in fields(salida_segura)} == {
        "aprobada",
        "codigos",
        "conteos",
    }
    assert salida_segura.codigos == ("INFORMACION_IDENTIFICABLE_RESIDUAL",)
    assert salida_segura.conteos == {"rechazados": 1}
