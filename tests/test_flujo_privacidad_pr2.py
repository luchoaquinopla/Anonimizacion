"""Pruebas RED del flujo de privacidad efímero de PR 2."""

import inspect
from importlib import import_module

entrada = import_module("ingesta_clinica.aplicacion.puertos.entrada")
salida = import_module("ingesta_clinica.aplicacion.puertos.salida")
extraccion = import_module("ingesta_clinica.dominio.extraccion")
privacidad = import_module("ingesta_clinica.dominio.privacidad")

PuertoEntradaIngesta = entrada.PuertoEntradaIngesta
crear_puerto_entrada_ingesta = import_module(
    "ingesta_clinica.composicion"
).crear_puerto_entrada_ingesta
ResultadoClasificacionFamilia = salida.ResultadoClasificacionFamilia
ResultadoExtraccion = extraccion.ResultadoExtraccion
ResolucionCampo = extraccion.ResolucionCampo


class ClasificadorLaboratorio:
    def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
        return ResultadoClasificacionFamilia(
            es_laboratorio=True,
            codigo_rechazo=None,
            procedencia={"numero_pagina": 1, "indice_bloque": 0},
            extraccion=ResultadoExtraccion(
                campos=(ResolucionCampo("marcador_laboratorio_alfa", "verificado"),),
                procedencia=None,
                codigos_campos_inventario={"marcador_laboratorio_alfa"},
            ),
        )


class AnonimizadorRegistrable:
    def __init__(self, eventos: list[str], salida: str) -> None:
        self.eventos = eventos
        self.salida = salida

    def anonimizar(self, contenido: bytes) -> str:
        self.eventos.append("anonimizacion")
        return self.salida


class ValidadorRegistrable:
    def __init__(self, eventos: list[str], aprobada: bool = True) -> None:
        self.eventos = eventos
        self.aprobada = aprobada

    def validar(self, contenido_anonimizado: str) -> object:
        self.eventos.append("validacion")
        return privacidad.ResultadoValidacionPrivacidad(
            aprobada=self.aprobada,
            codigo=(
                "PRIVACIDAD_VERIFICADA"
                if self.aprobada
                else "INFORMACION_IDENTIFICABLE_RESIDUAL"
            ),
        )


def crear_puerto(*, validador: object, anonimizador: object) -> PuertoEntradaIngesta:
    return PuertoEntradaIngesta(
        ClasificadorLaboratorio(),
        validador_privacidad=validador,
        anonimizador=anonimizador,
        codigos_campos_obligatorios={"marcador_laboratorio_alfa"},
    )


def test_anonimiza_antes_de_validar_con_un_validador_independiente_inyectado() -> None:
    eventos: list[str] = []
    resultado = crear_puerto(
        anonimizador=AnonimizadorRegistrable(eventos, "contenido_anonimizado"),
        validador=ValidadorRegistrable(eventos),
    ).ingerir(b"entrada_sintetica")

    assert eventos == ["anonimizacion", "validacion"]
    assert resultado.aprobada is True
    assert resultado.codigos == ("INGESTA_APROBADA",)


def test_hallazgo_residual_bloquea_y_no_filtra_el_contenido_transitorio() -> None:
    contenido_sensible_sintetico = "detalle_transitorio_no_permitido"
    resultado = crear_puerto(
        anonimizador=AnonimizadorRegistrable([], contenido_sensible_sintetico),
        validador=ValidadorRegistrable([], aprobada=False),
    ).ingerir(b"entrada_sintetica")

    assert resultado.aprobada is False
    assert resultado.codigos == ("INFORMACION_IDENTIFICABLE_RESIDUAL",)
    assert resultado.conteos == {"documentos_rechazados": 1}
    assert contenido_sensible_sintetico not in repr(resultado)


def test_campo_obligatorio_no_verificable_se_rechaza_con_codigo_seguro() -> None:
    class ClasificadorCampoIncompleto(ClasificadorLaboratorio):
        def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
            return ResultadoClasificacionFamilia(
                es_laboratorio=True,
                codigo_rechazo=None,
                procedencia=None,
                extraccion=ResultadoExtraccion(
                    campos=(ResolucionCampo("marcador_laboratorio_alfa", "faltante"),),
                    procedencia=None,
                ),
            )

    resultado = PuertoEntradaIngesta(
        ClasificadorCampoIncompleto(),
        validador_privacidad=ValidadorRegistrable([]),
        anonimizador=AnonimizadorRegistrable([], "anonimizado"),
        codigos_campos_obligatorios={"marcador_laboratorio_alfa"},
    ).ingerir(b"entrada_sintetica")

    assert resultado.aprobada is False
    assert resultado.codigos == ("CAMPO_OBLIGATORIO_NO_VERIFICABLE",)


def test_composicion_aplica_el_control_real_del_campo_obligatorio() -> None:
    resultado = crear_puerto_entrada_ingesta().ingerir(b"entrada_laboratorio_sintetica")

    assert resultado.aprobada is False
    assert resultado.codigos == ("CAMPO_OBLIGATORIO_NO_VERIFICABLE",)


def test_fallos_de_extraccion_y_validacion_se_convierten_en_rechazos_seguros() -> None:
    class ClasificadorFallido:
        def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
            raise RuntimeError("detalle_transitorio_no_permitido")

    resultado_extraccion = PuertoEntradaIngesta(ClasificadorFallido()).ingerir(
        b"entrada_sintetica"
    )
    assert resultado_extraccion.codigos == ("EXTRACCION_FALLIDA",)

    resultado_validacion = crear_puerto(
        anonimizador=AnonimizadorRegistrable([], "anonimizado"),
        validador=ValidadorFallido(),
    ).ingerir(b"entrada_sintetica")
    assert resultado_validacion.codigos == ("VALIDACION_PRIVACIDAD_FALLIDA",)
    assert "detalle_transitorio_no_permitido" not in repr(resultado_validacion)


def test_codigo_rechazo_del_adaptador_se_normaliza_a_catalogo_tecnico() -> None:
    class ClasificadorConRechazo:
        def __init__(self, codigo_rechazo: str | None) -> None:
            self.codigo_rechazo = codigo_rechazo

        def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
            return ResultadoClasificacionFamilia(
                es_laboratorio=False,
                codigo_rechazo=self.codigo_rechazo,
                procedencia=None,
                extraccion=None,
            )

    for codigo_adaptador, codigo_esperado in (
        ("detalle_transitorio_no_permitido", "FAMILIA_DOCUMENTO_NO_COMPATIBLE"),
        ("FAMILIA_DOCUMENTO_NO_COMPATIBLE", "FAMILIA_DOCUMENTO_NO_COMPATIBLE"),
        (
            "TABLA_LABORATORIO_SIN_FILAS_RESULTADO",
            "TABLA_LABORATORIO_SIN_FILAS_RESULTADO",
        ),
    ):
        resultado = PuertoEntradaIngesta(
            ClasificadorConRechazo(codigo_adaptador)
        ).ingerir(b"entrada_sintetica")

        assert resultado.codigos == (codigo_esperado,)
        assert (
            codigo_adaptador not in repr(resultado)
            or codigo_adaptador == codigo_esperado
        )


def test_flujo_no_abre_canales_laterales_de_escritura_o_registro() -> None:
    codigo_flujo = inspect.getsource(entrada)

    for dependencia_prohibida in ("logging", "pathlib", "sqlite", "requests", "queue"):
        assert dependencia_prohibida not in codigo_flujo


class ValidadorFallido:
    def validar(self, contenido_anonimizado: str) -> object:
        raise RuntimeError("detalle_transitorio_no_permitido")
