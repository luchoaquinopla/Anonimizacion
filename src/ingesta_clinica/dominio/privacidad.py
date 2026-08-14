"""Validación residual de privacidad sin exponer hallazgos."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResultadoValidacionPrivacidad:
    aprobada: bool
    codigo: str


@dataclass(frozen=True)
class SalidaTecnicaSegura:
    """Límite público: sólo decisión, códigos técnicos y conteos."""

    aprobada: bool
    codigos: tuple[str, ...]
    conteos: Mapping[str, int]


class PuertoAnonimizacion(Protocol):
    """Anonimiza contenido efímero antes del control residual independiente."""

    def anonimizar(self, contenido: bytes) -> str:
        """Devuelve contenido transitorio anonimizado."""
        raise NotImplementedError


class PuertoValidadorPrivacidad(Protocol):
    """Valida residuales sin depender de la etapa de anonimización."""

    def validar(self, contenido_anonimizado: str) -> ResultadoValidacionPrivacidad:
        """Devuelve únicamente la decisión técnica de privacidad."""
        raise NotImplementedError


class AnonimizadorBasico:
    """Elimina marcadores sintéticos identificables antes de validarlos."""

    _marcadores_a_eliminar = (
        "token_identificador_sintetico",
        "token_contacto_sintetico",
    )

    def anonimizar(self, contenido: bytes) -> str:
        texto = contenido.decode("utf-8", errors="ignore")
        for marcador in self._marcadores_a_eliminar:
            texto = texto.replace(marcador, "")
        return texto


class ValidadorPrivacidad:
    """Detecta marcadores residuales sintéticos sin retener la entrada."""

    _marcadores_residuales = frozenset(
        {"token_identificador_sintetico", "token_contacto_sintetico"}
    )

    def validar(self, contenido: str | bytes) -> ResultadoValidacionPrivacidad:
        texto = (
            contenido.decode("utf-8", errors="ignore")
            if isinstance(contenido, bytes)
            else contenido
        )
        if any(marcador in texto for marcador in self._marcadores_residuales):
            return ResultadoValidacionPrivacidad(
                aprobada=False, codigo="INFORMACION_IDENTIFICABLE_RESIDUAL"
            )
        return ResultadoValidacionPrivacidad(
            aprobada=True, codigo="PRIVACIDAD_VERIFICADA"
        )

    def salida_segura(
        self,
        aprobada: bool,
        codigos: tuple[str, ...],
        conteos: Mapping[str, int],
    ) -> SalidaTecnicaSegura:
        return SalidaTecnicaSegura(
            aprobada=aprobada, codigos=tuple(codigos), conteos=dict(conteos)
        )
