"""Representaciones efímeras de resultados de extracción."""

from collections.abc import Mapping
from dataclasses import dataclass

ESTADOS_EXTRACCION = frozenset(
    {
        "verificado",
        "no_presente",
        "faltante",
        "ambiguo",
        "malformado",
        "truncado",
    }
)


@dataclass(frozen=True)
class ResolucionCampo:
    """Estado explícito de un campo, sin conservar su valor."""

    codigo: str
    estado: str

    def __post_init__(self) -> None:
        if not self.codigo:
            raise ValueError("El código del campo es obligatorio.")
        if self.estado not in ESTADOS_EXTRACCION:
            raise ValueError("El estado de extracción no es válido.")


@dataclass(frozen=True)
class CandidatoCampo:
    """Señales de validez de un candidato, sin su valor ni texto de origen."""

    unidad_compatible: bool = True
    valor_malformado: bool = False
    valor_truncado: bool = False


class PoliticaResolucionCampo:
    """Reduce candidatos a un único estado explícito y seguro por campo."""

    def resolver(
        self, codigo: str, candidatos: tuple[CandidatoCampo, ...]
    ) -> ResolucionCampo:
        if not candidatos:
            return ResolucionCampo(codigo=codigo, estado="no_presente")
        if len(candidatos) > 1:
            return ResolucionCampo(codigo=codigo, estado="ambiguo")

        candidato = next(iter(candidatos))
        if candidato.valor_truncado:
            return ResolucionCampo(codigo=codigo, estado="truncado")
        if candidato.valor_malformado or not candidato.unidad_compatible:
            return ResolucionCampo(codigo=codigo, estado="malformado")
        return ResolucionCampo(codigo=codigo, estado="verificado")


@dataclass(frozen=True)
class ResultadoExtraccion:
    """Resultado transitorio que sólo conserva estados y procedencia técnica."""

    campos: tuple[ResolucionCampo, ...]
    procedencia: Mapping[str, int] | None
    codigos_campos_inventario: frozenset[str] | set[str] | None = None

    def __post_init__(self) -> None:
        codigos_resueltos = {resolucion.codigo for resolucion in self.campos}
        if len(codigos_resueltos) != len(self.campos):
            raise ValueError("Cada campo debe tener una única resolución explícita.")
        if self.codigos_campos_inventario is None:
            return

        codigos_inventario = frozenset(self.codigos_campos_inventario)
        if not codigos_inventario:
            raise ValueError("El inventario de campos no puede estar vacío.")
        if codigos_resueltos != codigos_inventario:
            raise ValueError(
                "Todo campo del inventario debe tener un estado explícito."
            )
        object.__setattr__(self, "codigos_campos_inventario", codigos_inventario)
