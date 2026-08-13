"""Puerto de entrada síncrono para ingesta efímera."""

from ingesta_clinica.aplicacion.puertos.salida import PuertoSalidaClasificacionFamilia
from ingesta_clinica.dominio.politica import PoliticaDecision
from ingesta_clinica.dominio.privacidad import SalidaTecnicaSegura, ValidadorPrivacidad


class PuertoEntradaIngesta:
    """Orquesta controles en memoria y devuelve únicamente un acuse seguro."""

    def __init__(
        self, clasificador_familia: PuertoSalidaClasificacionFamilia
    ) -> None:
        self._clasificador_familia = clasificador_familia

    def ingerir(self, contenido: bytes) -> SalidaTecnicaSegura:
        resultado_adaptador = self._clasificador_familia.extraer(contenido)
        if not resultado_adaptador.es_laboratorio:
            return SalidaTecnicaSegura(
                aprobada=False,
                codigos=("FAMILIA_DOCUMENTO_NO_COMPATIBLE",),
                conteos={"documentos_rechazados": 1},
            )

        assert resultado_adaptador.extraccion is not None
        validacion = ValidadorPrivacidad().validar(contenido)
        decision = PoliticaDecision().decidir(
            resultado_adaptador.extraccion,
            codigos_campos_obligatorios=frozenset(),
            controles_privacidad_completos=True,
            informacion_identificable_residual_encontrada=not validacion.aprobada,
        )
        codigos = decision.codigos or ("INGESTA_APROBADA",)
        conteos = {
            "documentos_aprobados" if decision.aprobada else "documentos_rechazados": 1
        }
        return SalidaTecnicaSegura(
            aprobada=decision.aprobada, codigos=codigos, conteos=conteos
        )
