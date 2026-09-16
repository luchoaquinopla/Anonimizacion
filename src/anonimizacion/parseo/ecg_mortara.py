"""Parser de ECG Mortara.
Tolera advertencias propias del equipo (p. ej. "PID / NAME MISMATCH"): se documentan como
flag no-PII en `adicionales`, nunca el texto crudo, y el resto del documento se parsea igual.

Recalibración contra el layout real (posicional, sin etiquetas "Campo: valor"; ver
`sdd/pdf-pii-anonymization/apply-progress`, sección "Fix: recalibración parser ECG contra
layout real Mortara"): agrega la extracción de `fecha_nac`, necesaria para el puente
`id_alt_paciente -> id_paciente` hacia el laboratorio.

Fix de medidas (regex + cuerpo real multilínea, ver la misma sección de apply-progress,
"#6"): `\b` agregado a los marcadores cortos que podían matchear como substring de otra
palabra (p. ej. "PR" dentro de "APR", mes en inglés); `_extraer_medida` prueba primero el
formato legado de una sola línea y si no encuentra valor busca en una ventana de líneas
vecinas (`_valor_en_ventana`/`_ejes_en_ventana`), fail-safe a `None` si no hay suficientes
valores contiguos. Calibrado contra una sola muestra real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time

from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, DetalleParseoIncompleto, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.senal_ecg import SenalEcg
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.senal_ecg import construir_senal
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.reconciliacion.base import ReferenciaCampo
from anonimizacion.reconciliacion.normalizacion import normalizar_hora_iso

_ETAPA = "parseo"
_VERSION_ESQUEMA = 1

_ADVERTENCIA_PID_MISMATCH = "PID / NAME MISMATCH"

# Formato real: `NOMBRE~,` ... `ID:<id>` ... `DD-MON-YYYY  HH:MM:SS` ... institución/reporte.
_CAMPOS_HEADER = {
    "nombre": r"(?m)^([^\n~]+?)~,",
    "id_estudio": r"ID:(\S+)",
    "fecha": r"(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})",
    "institucion": r"\d{2}:\d{2}:\d{2}\s+(.+)",
    # Fecha de nacimiento + edad + sexo comparten línea propia: `DD-MON-YYYY (NN yr) Male|Female`.
    "fecha_nac": r"(?m)^(\d{2}-[A-Za-z]{3}-\d{4})\s*\(\d+\s*yr\)",
    "edad": r"\((\d+)\s*yr\)",
    "sexo": r"(?i)\d{2}-[A-Za-z]{3}-\d{4}\s*\(\d+\s*yr\)\s+(Male|Female)",
    "tecnico": r"Technician:\s*(.*)",
    "test_ind": r"Test ind:\s*(.*)",
    "medico_derivante": r"Ordered by:\s*-?\s*(.+)",
}

# Medidas en una sola línea (formato legado) o etiqueta/valor separados (formato real, ver
# docstring del módulo). `\b` evita que un marcador corto matchee como substring de otra palabra.
_PATRON_VENT_RATE = re.compile(r"\bVent\.?\s*[Rr]ate\b\s*:?\s*(.*)")
_PATRON_PR_INTERVAL = re.compile(r"\bPR(?:\s*interval)?\b\s*:?\s*(.*)")
_PATRON_QRS_DURATION = re.compile(r"\bQRS(?:\s*duration)?\b\s*:?\s*(.*)")
_PATRON_QT_QTC = re.compile(r"\bQT/QTc\b\s*:?\s*(.*)")
_PATRON_EJES = re.compile(r"(?:Ejes\s*)?\bP-R-T\s*(?:axes)?\b\s*:?\s*(.*)")

# Token numérico puro para la búsqueda en ventana; admite un par separado por "/" (p.ej. QT/QTc).
_PATRON_VALOR_VENTANA = re.compile(
    r"^[+-]?\d+(?:[.,]\d+)?(?:/[+-]?\d+(?:[.,]\d+)?)?$"
)
# Sin "/": para el escaneo contiguo de "ejes", se detiene si encuentra algo no numérico simple.
_PATRON_VALOR_SIMPLE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")

_CAMPOS_HEADER_EXCLUIDOS_DE_ADICIONALES = ("nombre", "fecha", "id_estudio", "fecha_nac")


@dataclass(frozen=True)
class ContenidoEcg:
    """Payload tipado de las medidas de un ECG.
    `senal`: `None` si el layout de trazos no valida o no hay trazos capturados."""

    vent_rate: str | None
    pr_interval: str | None
    qrs_duration: str | None
    qt_qtc: str | None
    ejes: str | None
    senal: SenalEcg | None = None


def _buscar_campos(texto: str, patrones: dict[str, str]) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave, patron in patrones.items():
        coincidencia = re.search(patron, texto)
        if coincidencia:
            campos[clave] = coincidencia.group(1).strip()
    return campos


def _primer_segmento(texto: str) -> str:
    """Trunca en el primer salto de 2+ espacios (separador de columnas del reporte)."""
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _colapsar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _valor_en_ventana(lineas: list[str], indice_etiqueta: int) -> str | None:
    """Busca el token numérico más cercano a la etiqueta, offsets en orden de cercanía (±1,±2,±3)."""
    for offset in (-1, 1, -2, 2, -3, 3):
        indice = indice_etiqueta + offset
        if 0 <= indice < len(lineas):
            candidata = lineas[indice].strip()
            if _PATRON_VALOR_VENTANA.match(candidata):
                return candidata
    return None


def _ejes_en_ventana(lineas: list[str], indice_etiqueta: int) -> str | None:
    """Escanea líneas contiguas numéricas junto a "P-R-T axes"; `None` si hay menos de 2."""
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


def _parsear_fecha(texto: str) -> tuple[date, time, PrecisionHora]:
    """Separa fecha y hora del header (`DD-MON-YYYY  HH:MM:SS`).
    `ValueError` si la hora no matchea ningún formato soportado; el llamador la manda a cuarentena."""
    solo_fecha, _, porcion_hora = texto.strip().partition(" ")
    fecha = datetime.strptime(solo_fecha, "%d-%b-%Y").date()
    hora_normalizada, precision = normalizar_hora_iso(porcion_hora.strip())
    formato_hora = "%H:%M:%S" if precision is PrecisionHora.SEGUNDO else "%H:%M"
    hora = datetime.strptime(hora_normalizada, formato_hora).time()
    return fecha, hora, precision


def _parsear_fecha_nacimiento(texto: str) -> str | None:
    """Normaliza a ISO 8601 (`YYYY-MM-DD`) para que el puente `id_alt_paciente` sea canónico.
    Si no se puede parsear, se descarta en vez de propagar un formato crudo."""
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

        # Dos chequeos separados: nombre ausente y fecha ausente ameritan revisar cosas distintas.
        if "nombre" not in header:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
                etapa=_ETAPA,
                detalle_parseo=DetalleParseoIncompleto.NOMBRE_AUSENTE,
            )
        if "fecha" not in header:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
                etapa=_ETAPA,
                detalle_parseo=DetalleParseoIncompleto.FECHA_AUSENTE,
            )

        if "institucion" in header:
            header["institucion"] = _primer_segmento(header["institucion"])
        if "medico_derivante" in header:
            header["medico_derivante"] = _primer_segmento(header["medico_derivante"])

        try:
            fecha_estudio, hora_estudio, precision_hora = _parsear_fecha(header["fecha"])
        except ValueError as _exc:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
                etapa=_ETAPA,
                detalle_parseo=DetalleParseoIncompleto.FECHA_ILEGIBLE,
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
            # construir_senal(()) ya devuelve None sin caso especial si no hay trazos capturados.
            senal=construir_senal(texto.trazos),
        )
        fuentes = (
            ReferenciaCampo("ecg.nombre", 1, "ecg.nombre"),
            *((ReferenciaCampo("ecg.id_estudio", 1, "ecg.id_estudio"),) if identidad.ids_internos else ()),
            ReferenciaCampo("ecg.fecha_estudio", 1, "ecg.fecha_estudio"),
            ReferenciaCampo("ecg.hora_estudio", 1, "ecg.hora_estudio"),
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
            hora_estudio=hora_estudio,
            precision_hora=precision_hora,
            contenido=contenido,
            adicionales=adicionales,
            fuentes=fuentes,
        )
