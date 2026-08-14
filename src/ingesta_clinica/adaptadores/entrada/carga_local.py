"""Adaptador síncrono de lotes locales, sin retener contenido documental."""

from dataclasses import dataclass
from typing import Protocol

from ingesta_clinica.dominio.privacidad import SalidaTecnicaSegura


CODIGOS_ACUSE_PERMITIDOS = frozenset(
    {
        "INGESTA_APROBADA",
        "INGESTA_FALLIDA",
        "EXTRACCION_FALLIDA",
        "VALIDACION_PRIVACIDAD_FALLIDA",
        "FAMILIA_DOCUMENTO_NO_COMPATIBLE",
        "TABLA_LABORATORIO_SIN_FILAS_RESULTADO",
        "INFORMACION_IDENTIFICABLE_RESIDUAL",
        "CONTROLES_DE_PRIVACIDAD_INCOMPLETOS",
        "CAMPO_OBLIGATORIO_NO_VERIFICABLE",
    }
)
CODIGO_FALLO_LOTE_SEGURO = "INGESTA_FALLIDA"


class PuertoEntrada(Protocol):
    """El límite que consume el adaptador, independiente de la interfaz."""

    def ingerir(self, contenido: bytes) -> SalidaTecnicaSegura:
        """Procesa un único contenido efímero."""
        raise NotImplementedError


@dataclass(frozen=True)
class AcuseLoteSeguro:
    """Salida mínima: contadores y un código técnico seguro por archivo."""

    recibidos: int
    procesados: int
    codigos_por_archivo: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.recibidos < 0 or self.procesados != self.recibidos:
            raise ValueError("Los contadores del lote no son válidos.")
        if len(self.codigos_por_archivo) != self.procesados:
            raise ValueError("El acuse debe tener un código por archivo.")
        if not set(self.codigos_por_archivo) <= CODIGOS_ACUSE_PERMITIDOS:
            raise ValueError("El acuse contiene un código no permitido.")


class AdaptadorCargaLocal:
    """Invoca el puerto una vez por archivo y compone el acuse al terminar."""

    def __init__(self, puerto_entrada: PuertoEntrada) -> None:
        self._puerto_entrada = puerto_entrada

    def procesar_lote(self, contenidos: list[bytes]) -> AcuseLoteSeguro:
        """Procesa secuencialmente; no conserva contenido ni resultados internos."""
        codigos = [self._procesar_archivo(contenido) for contenido in contenidos]
        return AcuseLoteSeguro(
            recibidos=len(codigos),
            procesados=len(codigos),
            codigos_por_archivo=tuple(codigos),
        )

    def _procesar_archivo(self, contenido: bytes) -> str:
        try:
            resultado = self._puerto_entrada.ingerir(contenido)
            return self._codigo_seguro(resultado)
        except Exception:
            return CODIGO_FALLO_LOTE_SEGURO
        finally:
            contenido = b""
            resultado = None

    @staticmethod
    def _codigo_seguro(resultado: SalidaTecnicaSegura) -> str:
        codigo = resultado.codigos[0] if len(resultado.codigos) == 1 else None
        if codigo in CODIGOS_ACUSE_PERMITIDOS:
            return codigo
        return CODIGO_FALLO_LOTE_SEGURO
