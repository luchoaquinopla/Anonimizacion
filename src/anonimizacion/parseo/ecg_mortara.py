"""Parser de ECG Mortara (spec `document-parsing`).

El equipo Mortara a veces imprime advertencias propias en el PDF, como
"PID / NAME MISMATCH" (ID/nombre de paciente inconsistente entre dos
registros internos del propio equipo). El parser NO debe abortar por esto
(requirement "Parser de ECG tolerante a advertencias del equipo"): la
advertencia se documenta como un flag no-PII en `adicionales` — un código
fijo, nunca el texto crudo de la advertencia, siguiendo el mismo principio
de `dominio/errores.py` de no propagar mensajes crudos que podrían traer
PII — y el resto del documento se parsea con normalidad.

Recalibración post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`,
sección "Fix: recalibración parser ECG contra layout real Mortara"): el
layout REAL de un ECG Mortara es POSICIONAL, sin etiquetas "Campo: valor"
como se asumió inicialmente contra un formato sintético idealizado. Puntos
clave del formato real:

- El nombre aparece suelto al inicio de una línea, sin etiqueta, terminado
  en el artefacto propio del equipo `~,`.
- La fecha/hora del estudio y la fecha de nacimiento comparten el mismo
  formato `DD-MON-YYYY` (mes en inglés, 3 letras mayúsculas) — NO
  `DD/MM/YYYY`. La fecha de nacimiento viene acompañada de la edad entre
  paréntesis (`(NN yr)`) y el sexo (`Male`/`Female`), todo en la misma línea,
  sin etiquetas.
- Las medidas usan un punto después de "Vent" (`Vent. rate`) y nombres en
  inglés (`PR interval`, `QRS duration`, `P-R-T axes`), no los rótulos en
  español con dos puntos que se usaban en el formato sintético original.

Esta recalibración agrega la extracción de `fecha_nac` (antes SIEMPRE
`None`): es el dato que permite que `pseudonimizacion.claves.generar_id_alt_paciente`
calcule el puente `id_alt_paciente -> id_paciente` hacia el laboratorio
(ver `pseudonimizacion/resolutor_claves.py`, Fase 6) — sin esto, ningún ECG
real podía resolver su identidad vía el laboratorio.

Fix post-PR9 #6 (regex de medidas + cuerpo real multilínea, ver
`sdd/pdf-pii-anonymization/apply-progress`): dos problemas distintos en las
medidas contra 3 documentos reales:

1. `_CAMPOS_MEDIDAS["pr_interval"]` original no tenía `\b` (límite de
   palabra) antes de `"PR"` -- matchea la subcadena "PR" DENTRO de "APR"
   (mes en inglés de la fecha del estudio, p. ej. "13-APR-2026"), que
   aparece ANTES que la etiqueta real "PR interval" en el texto. Como
   `re.search` devuelve el primer match, el valor quedaba corrompido con el
   resto de la línea de fecha. Se agregó `\b` a TODOS los marcadores cortos
   de `_PATRON_*` que podrían aparecer como substring de otra palabra.

2. El layout real NUNCA trae etiqueta y valor en la misma línea, y el orden
   relativo valor/etiqueta varía por campo (a veces el valor va 1 línea
   ANTES de la etiqueta, a veces 1 línea DESPUÉS; "P-R-T axes" trae hasta 3
   valores numéricos varias líneas antes). Un regex de "etiqueta seguida de
   valor en la misma línea" nunca puede cubrir esto. `_extraer_medida`
   ahora: (a) intenta primero el formato legado de una sola línea (para no
   romper las fixtures sintéticas existentes); (b) si la etiqueta no trae
   valor en su propia línea, busca el token numérico más cercano en una
   ventana de líneas vecinas (`_valor_en_ventana`, offsets ±1/±2/±3,
   probados en ese orden de cercanía) — funciona para los campos de un solo
   valor (`vent_rate`/`pr_interval`/`qrs_duration`/`qt_qtc`) sin necesidad
   de codificar la dirección exacta por campo, porque el token más cercano
   siempre resulta ser el correcto contra la muestra real. Para `ejes`
   (tres valores en un campo, el caso más complejo) se usa un escaneo
   contiguo hacia atrás desde la etiqueta (`_ejes_en_ventana`) que se
   detiene apenas encuentra una línea no puramente numérica -- si encuentra
   menos de 2 valores contiguos, se prioriza devolver `None` (fail-safe)
   antes que un valor corrupto, mismo criterio que la firma del eco (fix
   #4). Calibrado contra una sola muestra real -- esta heurística de
   ventana podría no generalizar perfecto a otro layout de equipo/reporte.
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
from anonimizacion.reconciliacion.base import ReferenciaCampo

_ETAPA = "parseo"
_VERSION_ESQUEMA = 1

_ADVERTENCIA_PID_MISMATCH = "PID / NAME MISMATCH"

# Formato real: `NOMBRE~,` ... `ID:<id>` ... `DD-MON-YYYY  HH:MM:SS` ...
# institución/tipo de reporte, todo en una sola línea del header.
_CAMPOS_HEADER = {
    "nombre": r"(?m)^([^\n~]+?)~,",
    "id_estudio": r"ID:(\S+)",
    "fecha": r"(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})",
    "institucion": r"\d{2}:\d{2}:\d{2}\s+(.+)",
    # Fecha de nacimiento + edad + sexo comparten una línea propia, sin
    # etiquetas: `DD-MON-YYYY (NN yr)      Male|Female`.
    "fecha_nac": r"(?m)^(\d{2}-[A-Za-z]{3}-\d{4})\s*\(\d+\s*yr\)",
    "edad": r"\((\d+)\s*yr\)",
    "sexo": r"(?i)\d{2}-[A-Za-z]{3}-\d{4}\s*\(\d+\s*yr\)\s+(Male|Female)",
    "tecnico": r"Technician:\s*(.*)",
    "test_ind": r"Test ind:\s*(.*)",
    "medico_derivante": r"Ordered by:\s*-?\s*(.+)",
}

# Medidas: `Vent. rate            73    BPM` (formato legado, una sola
# línea) o etiqueta/valor en líneas separadas (formato real, ver docstring
# del módulo, Fix post-PR9 #6). `\b` antes de cada marcador corto evita que
# matchee como substring de otra palabra (p. ej. "PR" dentro de "APR", mes
# en inglés de la fecha del estudio).
_PATRON_VENT_RATE = re.compile(r"\bVent\.?\s*[Rr]ate\b\s*:?\s*(.*)")
_PATRON_PR_INTERVAL = re.compile(r"\bPR(?:\s*interval)?\b\s*:?\s*(.*)")
_PATRON_QRS_DURATION = re.compile(r"\bQRS(?:\s*duration)?\b\s*:?\s*(.*)")
_PATRON_QT_QTC = re.compile(r"\bQT/QTc\b\s*:?\s*(.*)")
_PATRON_EJES = re.compile(r"(?:Ejes\s*)?\bP-R-T\s*(?:axes)?\b\s*:?\s*(.*)")

# Token numérico "puro" (entero/decimal, con o sin signo) para la búsqueda
# en ventana; opcionalmente admite un par separado por "/" (p. ej.
# "382/420" de QT/QTc).
_PATRON_VALOR_VENTANA = re.compile(
    r"^[+-]?\d+(?:[.,]\d+)?(?:/[+-]?\d+(?:[.,]\d+)?)?$"
)
# Sin "/": usado para el escaneo contiguo de "ejes" -- se detiene apenas
# encuentra algo que no sea un número simple (p. ej. el "382/420" de
# QT/QTc, que podría estar en la línea inmediatamente anterior).
_PATRON_VALOR_SIMPLE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")

_CAMPOS_HEADER_EXCLUIDOS_DE_ADICIONALES = ("nombre", "fecha", "id_estudio", "fecha_nac")


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


def _primer_segmento(texto: str) -> str:
    """Trunca en el primer salto de 2+ espacios (separador de columnas del reporte).

    El header real empaqueta varias columnas en la misma línea sin
    delimitador explícito (p.ej. institución + tipo de reporte, o médico
    derivante + estado de confirmación) — 2+ espacios es el separador de
    columnas que el propio equipo usa para alinearlas visualmente.
    """
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _colapsar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _valor_en_ventana(lineas: list[str], indice_etiqueta: int) -> str | None:
    """Busca el token numérico más cercano a la línea de la etiqueta,
    probando offsets en orden de cercanía (±1, ±2, ±3). Ver docstring del
    módulo, Fix post-PR9 #6 -- calibrado contra una sola muestra real,
    podría no generalizar a un layout donde el valor esté más lejos."""
    for offset in (-1, 1, -2, 2, -3, 3):
        indice = indice_etiqueta + offset
        if 0 <= indice < len(lineas):
            candidata = lineas[indice].strip()
            if _PATRON_VALOR_VENTANA.match(candidata):
                return candidata
    return None


def _ejes_en_ventana(lineas: list[str], indice_etiqueta: int) -> str | None:
    """Escanea líneas contiguas puramente numéricas antes (o, si no hay
    ninguna, después) de la etiqueta "P-R-T axes" y las junta como los tres
    valores del eje. Fail-safe: con menos de 2 valores contiguos encontrados
    devuelve `None` en vez de un valor posiblemente corrupto (mismo
    criterio que la firma del eco, fix post-PR9 #4)."""
    valores: list[str] = []
    indice = indice_etiqueta - 1
    while indice >= 0 and _PATRON_VALOR_SIMPLE.match(lineas[indice].strip()):
        valores.append(lineas[indice].strip())
        indice -= 1
    if valores:
        valores.reverse()
    else:
        indice = indice_etiqueta + 1
        while indice < len(lineas) and _PATRON_VALOR_SIMPLE.match(lineas[indice].strip()):
            valores.append(lineas[indice].strip())
            indice += 1
    if len(valores) < 2:
        return None
    return " ".join(valores[:3])


def _extraer_medida(
    lineas: list[str], patron: re.Pattern[str], *, es_ejes: bool = False
) -> str | None:
    for indice, linea in enumerate(lineas):
        coincidencia = patron.search(linea)
        if not coincidencia:
            continue
        resto = coincidencia.group(1).strip()
        if resto and re.search(r"\d", resto):
            return _colapsar_espacios(resto)  # formato legado, una sola línea
        if es_ejes:
            return _ejes_en_ventana(lineas, indice)
        return _valor_en_ventana(lineas, indice)
    return None


def _extraer_medidas_ecg(texto_completo: str) -> dict[str, str]:
    lineas = texto_completo.splitlines()
    medidas: dict[str, str] = {}
    for clave, patron, es_ejes in (
        ("vent_rate", _PATRON_VENT_RATE, False),
        ("pr_interval", _PATRON_PR_INTERVAL, False),
        ("qrs_duration", _PATRON_QRS_DURATION, False),
        ("qt_qtc", _PATRON_QT_QTC, False),
        ("ejes", _PATRON_EJES, True),
    ):
        valor = _extraer_medida(lineas, patron, es_ejes=es_ejes)
        if valor is not None:
            medidas[clave] = valor
    return medidas


def _parsear_fecha(texto: str) -> date:
    solo_fecha = texto.strip().split(" ")[0]
    return datetime.strptime(solo_fecha, "%d-%b-%Y").date()


def _parsear_fecha_nacimiento(texto: str) -> str | None:
    """Normaliza a ISO 8601 (`YYYY-MM-DD`).

    El puente `id_alt_paciente` (`pseudonimizacion/claves.py`,
    `generar_id_alt_paciente`) usa el string de fecha de nacimiento tal cual
    dentro del mensaje HMAC — para que el ECG y el laboratorio del mismo
    paciente produzcan la MISMA clave hace falta una representación
    canónica, no el formato crudo de cada equipo (el ECG usa `DD-MON-YYYY`,
    el laboratorio usa `DD/MM/YYYY`, ver `parseo/laboratorio_general.py`).
    Si no se puede parsear, se descarta (no participa del puente) en vez de
    propagar un formato crudo que nunca podría matchear.
    """
    try:
        return datetime.strptime(texto.strip(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


class ParseadorEcgMortara:
    """Parser del layout de ECG Mortara; tolera advertencias del equipo."""

    tipo_documento = TipoDocumento.ECG

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        texto_completo = texto.texto_completo
        header = _buscar_campos(texto_completo, _CAMPOS_HEADER)
        medidas = _extraer_medidas_ecg(texto_completo)

        if "nombre" not in header or "fecha" not in header:
            raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)

        if "institucion" in header:
            header["institucion"] = _primer_segmento(header["institucion"])
        if "medico_derivante" in header:
            header["medico_derivante"] = _primer_segmento(header["medico_derivante"])

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
            dni=None,  # el ECG no trae DNI (ver design.md, decisión 1)
            fecha_nac=SecretStr(fecha_nac_normalizada) if fecha_nac_normalizada else None,
            ids_internos=(
                (SecretStr(header["id_estudio"]),) if header.get("id_estudio") else ()
            ),
        )

        adicionales: dict[str, object] = {
            clave: valor
            for clave, valor in header.items()
            if clave not in _CAMPOS_HEADER_EXCLUIDOS_DE_ADICIONALES
        }
        if _ADVERTENCIA_PID_MISMATCH in texto_completo.upper():
            adicionales["advertencia_equipo"] = "PID_NAME_MISMATCH"

        contenido = ContenidoEcg(
            vent_rate=_colapsar_espacios(medidas["vent_rate"]) if "vent_rate" in medidas else None,
            pr_interval=_colapsar_espacios(medidas["pr_interval"]) if "pr_interval" in medidas else None,
            qrs_duration=_colapsar_espacios(medidas["qrs_duration"]) if "qrs_duration" in medidas else None,
            qt_qtc=_colapsar_espacios(medidas["qt_qtc"]) if "qt_qtc" in medidas else None,
            ejes=_colapsar_espacios(medidas["ejes"]) if "ejes" in medidas else None,
        )
        fuentes = (
            ReferenciaCampo("ecg.nombre", 1, "ecg.nombre"),
            *((ReferenciaCampo("ecg.id_estudio", 1, "ecg.id_estudio"),) if identidad.ids_internos else ()),
            ReferenciaCampo("ecg.fecha_estudio", 1, "ecg.fecha_estudio"),
            *((ReferenciaCampo("ecg.fecha_nacimiento", 1, "ecg.fecha_nacimiento"),) if identidad.fecha_nac else ()),
        ) + tuple(
            ReferenciaCampo(f"ecg.{campo}", 1, f"ecg.{campo}")
            for campo, valor in (("vent_rate", contenido.vent_rate), ("pr_interval", contenido.pr_interval), ("qrs_duration", contenido.qrs_duration), ("qt_qtc", contenido.qt_qtc), ("ejes", contenido.ejes))
            if valor is not None
        )

        return DocumentoParseado(
            tipo_documento=TipoDocumento.ECG,
            version_esquema=_VERSION_ESQUEMA,
            identidad=identidad,
            fecha_estudio=fecha_estudio,
            contenido=contenido,
            adicionales=adicionales,
            fuentes=fuentes,
        )
