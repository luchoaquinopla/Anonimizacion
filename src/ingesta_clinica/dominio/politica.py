"""Política de decisión para privacidad y completitud."""

from dataclasses import dataclass
from .extraccion import ResultadoExtraccion


@dataclass(frozen=True)
class ResultadoDecision:
    """Decisión interna sin valores ni detalles de campos."""

    aprobada: bool
    codigos: tuple[str, ...]


class PoliticaDecision:
    """Bloquea toda condición que impida verificar privacidad o requeridos."""

    def decidir(
        self,
        resultado: ResultadoExtraccion,
        codigos_campos_obligatorios: set[str] | frozenset[str],
        controles_privacidad_completos: bool,
        informacion_identificable_residual_encontrada: bool,
    ) -> ResultadoDecision:
        codigos: list[str] = []
        if informacion_identificable_residual_encontrada:
            codigos.append("INFORMACION_IDENTIFICABLE_RESIDUAL")
        if not controles_privacidad_completos:
            codigos.append("CONTROLES_DE_PRIVACIDAD_INCOMPLETOS")

        estados_por_codigo = {
            resolucion.codigo: resolucion.estado for resolucion in resultado.campos
        }
        if any(
            estados_por_codigo.get(codigo) != "verificado"
            for codigo in codigos_campos_obligatorios
        ):
            codigos.append("CAMPO_OBLIGATORIO_NO_VERIFICABLE")

        return ResultadoDecision(aprobada=not codigos, codigos=tuple(codigos))
