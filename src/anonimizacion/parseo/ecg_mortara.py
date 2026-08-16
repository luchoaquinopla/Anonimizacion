"""Parser de ECG Mortara (spec `document-parsing`).

El equipo Mortara a veces imprime advertencias propias en el PDF, como
"PID / NAME MISMATCH" (ID/nombre de paciente inconsistente entre dos
registros internos del propio equipo). El parser NO debe abortar por esto
(requirement "Parser de ECG tolerante a advertencias del equipo"): la
advertencia se documenta como un flag no-PII en `adicionales` — un código
fijo, nunca el texto crudo de la advertencia, siguiendo el mismo principio
de `dominio/errores.py` de no propagar mensajes crudos que podrían traer
PII — y el resto del documento se parsea con normalidad.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

_ETAPA = "parseo"
_VERSION_ESQUEMA = 1

_ADVERTENCIA_PID_MISMATCH = "PID / NAME MISMATCH"

_CAMPOS_HEADER = {
    "nombre": r"Nombre:\s*(.+)",
    "id_estudio": r"ID Estudio:\s*(.+)",
    "fecha": r"Fecha:\s*(.+)",
    "institucion": r"Instituci[oó]n:\s*(.+)",
    "edad": r"Edad:\s*(.+)",
    "sexo": r"Sexo:\s*(.+)",
    "tecnico": r"T[eé]cnico:\s*(.+)",
    "medico_derivante": r"M[eé]dico derivante:\s*(.+)",
}

_CAMPOS_MEDIDAS = {
    "vent_rate": r"Vent\s*Rate:\s*(.+)",
    "pr_interval": r"PR:\s*(.+)",
    "qrs_duration": r"QRS:\s*(.+)",
    "qt_qtc": r"QT/QTc:\s*(.+)",
    "ejes": r"Ejes P-R-T:\s*(.+)",
}


@dataclass(frozen=True)
class ContenidoEcg:
    """Payload tipado de las medidas de un ECG."""

    vent_rate: str | None
    pr_interval: str | None
    qrs_duration: str | None
    qt_qtc: str | None
    ejes: str | None


def _buscar_campos(texto: str, patrones: dict[str, str]) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave, patron in patrones.items():
        coincidencia = re.search(patron, texto)
        if coincidencia:
            campos[clave] = coincidencia.group(1).strip()
    return campos


def _parsear_fecha(texto: str) -> date:
    solo_fecha = texto.strip().split(" ")[0]
    return datetime.strptime(solo_fecha, "%d/%m/%Y").date()


class ParseadorEcgMortara:
    """Parser del layout de ECG Mortara; tolera advertencias del equipo."""

    tipo_documento = TipoDocumento.ECG

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        texto_completo = texto.texto_completo
        header = _buscar_campos(texto_completo, _CAMPOS_HEADER)
        medidas = _buscar_campos(texto_completo, _CAMPOS_MEDIDAS)

        if "nombre" not in header or "fecha" not in header:
            raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)

        try:
            fecha_estudio = _parsear_fecha(header["fecha"])
        except ValueError as _exc:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA
            ) from _exc

        identidad = IdentidadCruda(
            nombre=SecretStr(header["nombre"]),
            dni=None,  # el ECG no trae DNI (ver design.md, decisión 1)
            fecha_nac=None,
            ids_internos=(
                (SecretStr(header["id_estudio"]),) if header.get("id_estudio") else ()
            ),
        )

        adicionales: dict[str, object] = {
            clave: valor
            for clave, valor in header.items()
            if clave not in ("nombre", "fecha", "id_estudio")
        }
        if _ADVERTENCIA_PID_MISMATCH in texto_completo.upper():
            adicionales["advertencia_equipo"] = "PID_NAME_MISMATCH"

        contenido = ContenidoEcg(
            vent_rate=medidas.get("vent_rate"),
            pr_interval=medidas.get("pr_interval"),
            qrs_duration=medidas.get("qrs_duration"),
            qt_qtc=medidas.get("qt_qtc"),
            ejes=medidas.get("ejes"),
        )

        return DocumentoParseado(
            tipo_documento=TipoDocumento.ECG,
            version_esquema=_VERSION_ESQUEMA,
            identidad=identidad,
            fecha_estudio=fecha_estudio,
            contenido=contenido,
            adicionales=adicionales,
        )
