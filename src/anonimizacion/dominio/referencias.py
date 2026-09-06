"""Whitelist de IDs no sensibles permitidos para trazabilidad."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_IDENTIFICADOR_SEGURO = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")

REFERENCIAS_PERMITIDAS: dict[str, frozenset[str]] = {
    "ecg.nombre": frozenset({"ecg.nombre"}),
    "ecg.id_estudio": frozenset({"ecg.id_estudio"}),
    "ecg.fecha_estudio": frozenset({"ecg.fecha_estudio"}),
    "ecg.hora_estudio": frozenset({"ecg.hora_estudio"}),
    "ecg.fecha_nacimiento": frozenset({"ecg.fecha_nacimiento"}),
    "ecg.vent_rate": frozenset({"ecg.vent_rate"}),
    "ecg.pr_interval": frozenset({"ecg.pr_interval"}),
    "ecg.qrs_duration": frozenset({"ecg.qrs_duration"}),
    "ecg.qt_qtc": frozenset({"ecg.qt_qtc"}),
    "ecg.ejes": frozenset({"ecg.ejes"}),
    "laboratorio.nombre": frozenset({"laboratorio.nombre"}),
    "laboratorio.dni": frozenset({"laboratorio.dni"}),
    "laboratorio.fecha_estudio": frozenset({"laboratorio.fecha_estudio"}),
    "laboratorio.hora_extraccion": frozenset({"laboratorio.hora_extraccion"}),
    "laboratorio.resultado": frozenset({"laboratorio.resultado"}),
    "eco.nombre": frozenset({"eco.nombre"}),
    "eco.dni": frozenset({"eco.dni"}),
    "eco.fecha_estudio": frozenset({"eco.fecha_estudio"}),
    "eco.numero_estudio": frozenset({"eco.numero_estudio"}),
    "eco.medida": frozenset({
        "eco.medida.ao",
        "eco.medida.ai",
        "eco.medida.ddvi",
        "eco.medida.dsvi",
        "eco.medida.fa",
        "eco.medida.septum",
        "eco.medida.p.posterior",
        "eco.medida.no_catalogada",
    }),
    "eco.seccion": frozenset({"eco.seccion"}),
    "eco.firma": frozenset({"eco.firma"}),
}

_SELECTORES_MEDIDAS_ECO = {
    "ao": "eco.medida.ao",
    "ai": "eco.medida.ai",
    "ddvi": "eco.medida.ddvi",
    "dsvi": "eco.medida.dsvi",
    "fa": "eco.medida.fa",
    "septum": "eco.medida.septum",
    "p.posterior": "eco.medida.p.posterior",
}


def selector_medida_eco(nombre: str) -> str:
    """Construye un selector seguro a partir de la etiqueta, nunca del valor."""
    sin_acentos = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    etiqueta = re.sub(r"[^a-z0-9]+", ".", sin_acentos.lower()).strip(".")
    return _SELECTORES_MEDIDAS_ECO.get(etiqueta, "eco.medida.no_catalogada")


def validar_selector_reconciliacion(campo: str, selector: str) -> None:
    """Acepta selectores declarados y medidas Eco ancladas a su etiqueta."""
    if selector not in REFERENCIAS_PERMITIDAS[campo]:
        raise ValueError("selector inválido")


def validar_campo_reconciliacion(campo: str) -> None:
    """Acepta solo IDs declarados, nunca contenido de un documento."""
    if not _IDENTIFICADOR_SEGURO.fullmatch(campo) or campo not in REFERENCIAS_PERMITIDAS:
        raise ValueError("campo inválido")


# `ReferenciaCampo` y `HallazgoCobertura` viven en el dominio, no en
# `reconciliacion`, porque son value objects de localización: dónde cae un
# campo dentro del texto extraído (página, selector, ordinal), sin retener
# contenido ni PII. No son infraestructura de reconciliación, son datos del
# dominio como cualquier otro modelo de `dominio/modelos.py`. Antes vivían en
# `reconciliacion/base.py`, que a su vez depende de `DocumentoParseado`
# (`dominio/modelos.py`) — un ciclo real, oculto porque `modelos.py` diferia
# el import bajo `TYPE_CHECKING` y dentro de `__post_init__`. Moverlos acá
# rompe el ciclo sin cambiar el contrato: `reconciliacion/base.py` los
# reimporta desde este módulo.
@dataclass(frozen=True)
class ReferenciaCampo:
    """Localización no sensible de un campo dentro del texto extraído."""

    id_campo: str
    pagina: int
    selector: str
    ordinal: int = 0

    def __post_init__(self) -> None:
        validar_campo_reconciliacion(self.id_campo)
        validar_selector_reconciliacion(self.id_campo, self.selector)
        if self.pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        if self.ordinal < 0:
            raise ValueError("ordinal no puede ser negativo")


@dataclass(frozen=True)
class HallazgoCobertura:
    """Dato clínico reconocido sin retener su contenido ni PII."""

    id_campo: str
    pagina: int
    ordinal: int = 0
    clase: str = "dato"

    def __post_init__(self) -> None:
        validar_campo_reconciliacion(self.id_campo)
        if self.pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        if self.ordinal < 0:
            raise ValueError("ordinal no puede ser negativo")
        if self.clase not in {"dato", "header", "medida", "coleccion", "seccion"}:
            raise ValueError("clase inválida")
