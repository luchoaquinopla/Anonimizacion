"""Parser de laboratorio general (spec `document-parsing`).

Los PDFs reales son multipágina con el header repetido en cada página y las
secciones de resultados (HEMATOLOGIA, HEMOSTASIA, QUÍMICA CLÍNICA, IONOGRAMA)
repartidas entre ellas. El parser reconcilia todas las páginas en un único
`DocumentoParseado` por Nº de Petición: toma el header de la primera página
que lo trae completo, valida que el Nº de Petición no cambie entre páginas
(si cambia, son dos estudios mezclados por error de escaneo/orden — falla
explícito en vez de mezclar resultados de dos pacientes) y concatena las
filas de resultado de TODAS las páginas en un único `ContenidoLaboratorio`.

Nota de formato: el layout real de columnas (Resultado Actual/Unidades/
Valores de Referencia) todavía no está calibrado contra el corpus real (ver
design.md, "Pendientes"). Estos parsers asumen un separador `|` explícito
por fila de resultado como formato de trabajo estable y sin ambigüedad de
espacios; se recalibra contra PDFs reales sin cambiar la forma pública del
parser (misma entrada `TextoExtraido`, misma salida `DocumentoParseado`).
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

_SECCIONES = ("HEMATOLOGIA", "HEMOSTASIA", "QUIMICA CLINICA", "IONOGRAMA")

_CAMPOS_HEADER = {
    "nombre": r"Apellido y Nombre:\s*(.+)",
    "dni": r"DNI:\s*(.+)",
    "fecha_nac": r"F\.Nacimiento:\s*(.+)",
    "edad": r"Edad:\s*(.+)",
    "medico_derivante": r"M[eé]dico derivante:\s*(.+)",
    "numero_peticion": r"N[ºo°]\s*Petici[oó]n:\s*(.+)",
    "fecha": r"Fecha:\s*(.+)",
    "hora_extraccion": r"Hora Extracci[oó]n:\s*(.+)",
    "origen": r"Origen:\s*(.+)",
}


@dataclass(frozen=True)
class ResultadoLaboratorio:
    """Una fila de resultado dentro de una sección (HEMATOLOGIA, etc.)."""

    seccion: str
    prueba: str
    resultado: str
    unidades: str | None
    valores_referencia: str | None


@dataclass(frozen=True)
class ContenidoLaboratorio:
    """Payload tipado de un documento de laboratorio ya reconciliado."""

    numero_peticion: str
    resultados: tuple[ResultadoLaboratorio, ...]


def _extraer_campos_header(pagina: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave, patron in _CAMPOS_HEADER.items():
        coincidencia = re.search(patron, pagina)
        if coincidencia:
            campos[clave] = coincidencia.group(1).strip()
    return campos


def _parsear_fecha(texto: str) -> date:
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def _parsear_fecha_nacimiento(texto: str) -> str | None:
    """Normaliza `F.Nacimiento` a ISO 8601 (`YYYY-MM-DD`).

    Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
    "Fix: recalibración parser ECG contra layout real Mortara"): el puente
    `id_alt_paciente -> id_paciente` (`pseudonimizacion/claves.py`,
    `generar_id_alt_paciente`) usa el string de fecha de nacimiento tal cual
    dentro del mensaje HMAC. El laboratorio trae `DD/MM/YYYY` pero el ECG
    (`parseo/ecg_mortara.py`) trae `DD-MON-YYYY` — sin normalizar ambos a la
    misma representación canónica, el mismo paciente real produciría dos
    `id_alt_paciente` distintos y el puente nunca resolvería. Si no se puede
    parsear, se descarta (no participa del puente) en vez de propagar un
    formato crudo inconsistente.
    """
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _extraer_resultados(pagina: str) -> tuple[ResultadoLaboratorio, ...]:
    resultados: list[ResultadoLaboratorio] = []
    seccion_actual: str | None = None
    for linea in pagina.splitlines():
        linea_limpia = linea.strip()
        if not linea_limpia:
            continue
        candidata = linea_limpia.upper()
        if candidata in _SECCIONES:
            seccion_actual = candidata
            continue
        if seccion_actual is None or "|" not in linea_limpia:
            continue
        partes = [parte.strip() for parte in linea_limpia.split("|")]
        if len(partes) < 2:
            continue
        unidades = partes[2] if len(partes) > 2 and partes[2] else None
        valores_referencia = partes[3] if len(partes) > 3 and partes[3] else None
        resultados.append(
            ResultadoLaboratorio(
                seccion=seccion_actual,
                prueba=partes[0],
                resultado=partes[1],
                unidades=unidades,
                valores_referencia=valores_referencia,
            )
        )
    return tuple(resultados)


class ParseadorLaboratorioGeneral:
    """Parser del layout de laboratorio general; reconcilia header multi-página."""

    tipo_documento = TipoDocumento.LABORATORIO

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        header: dict[str, str] | None = None
        resultados: list[ResultadoLaboratorio] = []

        for pagina in texto.paginas:
            campos_pagina = _extraer_campos_header(pagina)
            numero_peticion_pagina = campos_pagina.get("numero_peticion")

            if numero_peticion_pagina:
                if header is None:
                    header = campos_pagina
                elif numero_peticion_pagina != header.get("numero_peticion"):
                    raise ErrorParseo(
                        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA
                    )

            resultados.extend(_extraer_resultados(pagina))

        if header is None or "nombre" not in header or "fecha" not in header:
            raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)

        try:
            fecha_estudio = _parsear_fecha(header["fecha"])
        except ValueError as _exc:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA
            ) from _exc

        fecha_nac_normalizada = (
            _parsear_fecha_nacimiento(header["fecha_nac"]) if header.get("fecha_nac") else None
        )

        identidad = IdentidadCruda(
            nombre=SecretStr(header["nombre"]),
            dni=SecretStr(header["dni"]) if header.get("dni") else None,
            fecha_nac=SecretStr(fecha_nac_normalizada) if fecha_nac_normalizada else None,
            ids_internos=(
                (SecretStr(header["numero_peticion"]),)
                if header.get("numero_peticion")
                else ()
            ),
        )

        adicionales = {
            clave: valor
            for clave, valor in header.items()
            if clave not in ("nombre", "dni", "fecha_nac", "fecha", "numero_peticion")
        }

        contenido = ContenidoLaboratorio(
            numero_peticion=header.get("numero_peticion", ""),
            resultados=tuple(resultados),
        )

        return DocumentoParseado(
            tipo_documento=TipoDocumento.LABORATORIO,
            version_esquema=_VERSION_ESQUEMA,
            identidad=identidad,
            fecha_estudio=fecha_estudio,
            contenido=contenido,
            adicionales=adicionales,
        )
