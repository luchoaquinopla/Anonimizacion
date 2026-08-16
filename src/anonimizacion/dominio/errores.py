"""Jerarquía de errores del dominio.

Ningún error transporta el mensaje crudo de la excepción original: podría
contener PII (ver design.md, decisión "Sin PII en cola, logs ni DLQ").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CodigoErrorDocumento(str, Enum):
    """Códigos de fallo terminal — todos van a cuarentena.

    Los primeros cuatro son determinísticos: nunca se reintentan, un
    reproceso sin cambios produce el mismo fallo (ver design.md,
    "Aislamiento de fallo y política de reintentos"). `ERROR_TRANSITORIO_AGOTADO`
    es distinto: se alcanza después de agotar los reintentos de un error
    transitorio (IO/conexión) -- ver `pipeline/ejecutor.py`. Reprocesar ESE
    documento más tarde puede tener éxito (el error original no era
    determinístico), a diferencia de los otros cuatro.
    """

    TIPO_NO_RECONOCIDO = "tipo_no_reconocido"
    PARSEO_INCOMPLETO = "parseo_incompleto"
    CLAVE_PII_NO_RESUELTA = "clave_pii_no_resuelta"
    # Hay más de un `id_paciente` candidato para el mismo `id_alt_paciente`
    # (homónimos: mismo nombre+fecha_nac, DNI distinto). A diferencia de
    # CLAVE_PII_NO_RESUELTA (todavía no hay ningún puente, reprocesar más
    # tarde puede resolverlo solo), esto requiere revisión manual --
    # reprocesar no lo arregla.
    CLAVE_PII_AMBIGUA = "clave_pii_ambigua"
    # Ver docstring de la clase: terminal tras agotar reintentos de un error
    # transitorio (`pipeline/ejecutor.py`, `trabajadores/politica_reintentos.py`).
    ERROR_TRANSITORIO_AGOTADO = "error_transitorio_agotado"


@dataclass(frozen=True)
class ErrorDocumento:
    """Registro terminal de fallo por documento; sin mensaje crudo, solo código."""

    id_documento: str
    etapa: str
    codigo: CodigoErrorDocumento


class ErrorParseo(Exception):
    """Error tipado que lanza cualquier etapa; el `codigo` reemplaza al mensaje crudo.

    `etapa` es obligatorio (sin default): el código puede originarse en detección,
    parseo o pseudonimización, y un default fijo llevaría a cuarentena mal etiquetada.
    """

    def __init__(self, codigo: CodigoErrorDocumento, etapa: str) -> None:
        self.codigo = codigo
        self.etapa = etapa
        super().__init__(codigo.value)  # str(excepcion) legible; codigo.value, no el enum repr
