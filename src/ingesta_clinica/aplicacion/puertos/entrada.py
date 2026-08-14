"""Puerto de entrada síncrono para ingesta efímera."""

from ingesta_clinica.aplicacion.puertos.salida import (
    PuertoSalidaClasificacionFamilia,
)
from ingesta_clinica.dominio.politica import PoliticaDecision
from ingesta_clinica.dominio.privacidad import (
    AnonimizadorBasico,
    PuertoAnonimizacion,
    PuertoValidadorPrivacidad,
    SalidaTecnicaSegura,
    ValidadorPrivacidad,
)


CODIGOS_RECHAZO_ADAPTADOR_PERMITIDOS = frozenset(
    {
        "FAMILIA_DOCUMENTO_NO_COMPATIBLE",
        "TABLA_LABORATORIO_SIN_FILAS_RESULTADO",
    }
)
CODIGO_RECHAZO_ADAPTADOR_SEGURO = "FAMILIA_DOCUMENTO_NO_COMPATIBLE"


class PuertoEntradaIngesta:
    """Orquesta controles en memoria y devuelve únicamente un acuse seguro."""

    def __init__(
        self,
        clasificador_familia: PuertoSalidaClasificacionFamilia,
        *,
        validador_privacidad: PuertoValidadorPrivacidad | None = None,
        anonimizador: PuertoAnonimizacion | None = None,
        codigos_campos_obligatorios: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        self._clasificador_familia = clasificador_familia
        self._validador_privacidad = validador_privacidad or ValidadorPrivacidad()
        self._anonimizador = anonimizador or AnonimizadorBasico()
        self._codigos_campos_obligatorios = frozenset(codigos_campos_obligatorios)

    def ingerir(self, contenido: bytes) -> SalidaTecnicaSegura:
        """Completa controles obligatorios y descarta referencias transitorias."""
        try:
            resultado_adaptador = self._clasificador_familia.extraer(contenido)
        except Exception:
            return self._rechazo("EXTRACCION_FALLIDA")

        if not resultado_adaptador.es_laboratorio:
            return self._rechazo(
                self._normalizar_codigo_rechazo_adaptador(
                    resultado_adaptador.codigo_rechazo
                )
            )

        if resultado_adaptador.extraccion is None:
            return self._rechazo("EXTRACCION_FALLIDA")

        try:
            contenido_anonimizado = self._anonimizador.anonimizar(contenido)
            validacion = self._validador_privacidad.validar(contenido_anonimizado)
            decision = PoliticaDecision().decidir(
                resultado_adaptador.extraccion,
                codigos_campos_obligatorios=self._codigos_campos_obligatorios,
                controles_privacidad_completos=True,
                informacion_identificable_residual_encontrada=not validacion.aprobada,
            )
            codigos = decision.codigos or ("INGESTA_APROBADA",)
            return SalidaTecnicaSegura(
                aprobada=decision.aprobada,
                codigos=codigos,
                conteos={
                    "documentos_aprobados"
                    if decision.aprobada
                    else "documentos_rechazados": 1
                },
            )
        except Exception:
            return self._rechazo("VALIDACION_PRIVACIDAD_FALLIDA")
        finally:
            contenido_anonimizado = None
            resultado_adaptador = None
            contenido = b""

    @staticmethod
    def _normalizar_codigo_rechazo_adaptador(codigo: str | None) -> str:
        if codigo in CODIGOS_RECHAZO_ADAPTADOR_PERMITIDOS:
            return codigo
        return CODIGO_RECHAZO_ADAPTADOR_SEGURO

    @staticmethod
    def _rechazo(codigo: str) -> SalidaTecnicaSegura:
        return SalidaTecnicaSegura(
            aprobada=False,
            codigos=(codigo,),
            conteos={"documentos_rechazados": 1},
        )
