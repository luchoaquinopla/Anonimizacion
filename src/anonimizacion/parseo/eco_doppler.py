"""Parser de ecocardiograma Doppler.
Separa medidas estructuradas y texto libre por sección en campos distintos de `ContenidoEco`,
más la firma del médico informante.

Fix (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix: extracción con sort=True +
firmas ECG reales"): el header se busca sobre `texto.texto_completo_ordenado` (orden
geométrico), no `texto.texto_completo`.

Fix #4 (recalibración lab/eco contra 3 documentos reales, misma sección de apply-progress):
header real usa `PACIENTE:`/`Fecha Estudio:`; medidas en tabla de dos sub-columnas por 2+
espacios; secciones anidadas en dos niveles; firma sin etiqueta "Firma:", detectada por
heurística de última línea nombre-like antes de la línea de Matrícula. Calibrado contra una
sola muestra real de cada tipo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, DetalleParseoIncompleto, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.referencias import selector_medida_eco
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.reconciliacion.base import ReferenciaCampo

_ETAPA = "parseo"
_VERSION_ESQUEMA = 1

_SECCIONES_TEXTO = (
    "MOTILIDAD SEGMENTARIA",
    "VALVULAS CARDIACAS",
    "AURICULAS",
    "PERICARDIO",
    "EVALUACION DE FLUJOS POR DOPPLER",
    "CONCLUSIONES",
)
_SECCION_MEDIDAS = "MEDIDAS"

# Fix #4 (recalibración lab/eco contra 3 documentos reales, ver
# `sdd/pdf-pii-anonymization/apply-progress`): el documento real anida subsecciones dentro
# de secciones de texto libre; cada subsección se representa como su propia `SeccionTextoEco`
# con nombre compuesto "padre - hija" (sin cambiar el modelo plano). Calibrado contra una muestra.
_SUBSECCIONES: dict[str, tuple[str, ...]] = {
    "VALVULAS CARDIACAS": ("AORTICA", "MITRAL", "PULMONAR", "TRICUSPIDEA"),
    "AURICULAS": ("IZQUIERDA", "DERECHA"),
    "EVALUACION DE FLUJOS POR DOPPLER": (
        "FLUJO AORTICO",
        "FLUJO MITRAL",
        "FLUJO PULMONAR",
        "FLUJO TRICUSPIDEO",
    ),
}

_CAMPOS_HEADER = {
    "nombre": r"(?i)Paciente:\s*(.+)",
    "dni": r"Documento:\s*(.+)",
    "numero_estudio": r"(?i)N[ºo°]\s*Estudio:\s*(.+)",
    # Fecha estricta (no `.+`): comparte fila con "PACIENTE:" separado por un solo espacio.
    "fecha": r"Fecha Estudio:\s*(\d{1,2}/\d{1,2}/\d{4})",
    "edad": r"Edad:\s*(.+)",
    "medico_solicitante": r"M[eé]dico Solicitante:\s*(.+)",
    "peso": r"Peso:\s*(.+)",
    "altura": r"Altura:\s*(.+)",
    "superficie_corporal": r"S\.C\.\s*:?\s*(.+)",
}

_PATRON_FIRMA = re.compile(r"Firma:\s*(?P<nombre>.+?)\s*-\s*MP\s*(?P<matricula>\S+)")

# Fix #4: el documento real no trae "Firma:"; el nombre va en línea propia (mayúsculas) y
# "Matrícula <letra> <número>" en una línea posterior. Heurística: última línea nombre-like
# antes de la matrícula; sin candidato previo, `firma` queda en `None` (prioriza no encontrar
# sobre encontrar mal). Calibrado contra una sola muestra real.
_PATRON_MATRICULA = re.compile(r"Matr[ií]cula\s+([A-Za-z])\s*(\d+)", re.IGNORECASE)
_PATRON_NOMBRE_FIRMA = re.compile(r"^[A-ZÁÉÍÓÚÑ.]+(?:\s+[A-ZÁÉÍÓÚÑ.]+)+$")
_TEXTO_FIRMA_EXCLUIDO = {"DIAGNOSTICO POR IMAGENES"}
_PREFIJOS_BOILERPLATE = (
    "servicio de ecocardiografia",
    "ecografia doppler color cardiaca",
    "instituto de cardiologia",
    "funcacorr",
    "fundacion cardiologica",
    "paciente:",
    "documento:",
    "fecha estudio:",
    "edad:",
    "nº estudio:",
    "n° estudio:",
    "no estudio:",
    "medico solicitante:",
    "médico solicitante:",
    "informe no valido",
    "informe no válido",
    "pagina ",
    "pag.:",
    "bolivar ",
    "e-mail:",
    "documento sintetico - solo pruebas",
)


@dataclass(frozen=True)
class MedidaEco:
    """Una medida estructurada (AO, FA, Septum, etc.)."""

    nombre: str
    valor: str
    unidad: str | None


@dataclass(frozen=True)
class SeccionTextoEco:
    """Texto libre dictado por sección (motilidad, válvulas, conclusiones, etc.)."""

    nombre: str
    texto: str


@dataclass(frozen=True)
class FirmaMedico:
    """Firma del médico informante: nombre + matrícula."""

    nombre: str
    matricula: str


@dataclass(frozen=True)
class ContenidoEco:
    """Payload tipado de un ecocardiograma: medidas + texto libre + firma."""

    medidas: tuple[MedidaEco, ...]
    secciones_texto: tuple[SeccionTextoEco, ...]
    firma: FirmaMedico | None


@dataclass(frozen=True)
class _CuerpoEco:
    medidas: tuple[MedidaEco, ...]
    paginas_medidas: tuple[int, ...]
    secciones: tuple[SeccionTextoEco, ...]
    paginas_secciones: tuple[int, ...]
    firma: FirmaMedico | None
    pagina_firma: int | None


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(caracter for caracter in descompuesto if not unicodedata.combining(caracter))


def es_boilerplate_eco(linea: str) -> bool:
    """Reconoce cabecera/pie repetidos sin aceptar texto clínico libre.
    Le saca los acentos a `linea` antes de comparar: `casefold()` sólo normaliza mayúsculas."""
    normalizada = " ".join(_sin_acentos(linea.strip()).casefold().split())
    return normalizada.startswith(_PREFIJOS_BOILERPLATE)


def _primer_segmento(texto: str) -> str:
    """Trunca en el primer salto de 2+ espacios (separador de columnas del reporte)."""
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _buscar_campos(texto: str, patrones: dict[str, str]) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave, patron in patrones.items():
        coincidencia = re.search(patron, texto)
        if coincidencia:
            campos[clave] = _primer_segmento(coincidencia.group(1))
    return campos


def _parsear_fecha(texto: str) -> date:
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def _es_nombre_de_medida(token: str) -> bool:
    """Un token de la tabla de medidas que parece nombre (letras/puntos, sin dígitos).
    Excluye "NORMAL"/"VARIABLE": son valores/rangos de referencia, no nombres de medida."""
    token_norm = token.strip().upper()
    if token_norm in {"NORMAL", "VARIABLE"}:
        return False
    return bool(re.fullmatch(r"[A-ZÁÉÍÓÚÑ.]+", token_norm))


def _separar_valor_unidad(token: str) -> tuple[str, str | None]:
    """Separa `"36 mm"` -> `("36", "mm")`; `"NORMAL"` -> `("NORMAL", None)`."""
    coincidencia = re.match(r"^(-?\d+[.,]?\d*)\s*(\S+)?$", token.strip())
    if not coincidencia:
        return token.strip(), None
    valor = coincidencia.group(1)
    unidad = coincidencia.group(2)
    return valor, unidad


def _parsear_fila_medidas_dos_columnas(linea: str) -> list[MedidaEco]:
    """Parsea una fila de la tabla real: dos sub-columnas separadas por 2+ espacios.
    El rango de referencia (p. ej. "< 41 mm") se descarta explícitamente, sin campo para guardarlo."""
    tokens = [token for token in re.split(r"\s{2,}", linea.strip()) if token]
    medidas: list[MedidaEco] = []
    indice = 0
    while indice < len(tokens):
        nombre = tokens[indice]
        indice += 1
        if not _es_nombre_de_medida(nombre) or indice >= len(tokens):
            continue
        valor_crudo = tokens[indice]
        indice += 1
        if indice < len(tokens) and not _es_nombre_de_medida(tokens[indice]):
            indice += 1  # rango de referencia, descartado
        valor, unidad = _separar_valor_unidad(valor_crudo)
        medidas.append(MedidaEco(nombre=nombre, valor=valor, unidad=unidad))
    return medidas


def _parsear_cuerpo(  # noqa: C901 -- deuda conocida, ver pyproject.toml
    paginas: tuple[str, ...],
) -> _CuerpoEco:
    medidas: list[MedidaEco] = []
    paginas_medidas: list[int] = []
    secciones: list[SeccionTextoEco] = []
    paginas_secciones: list[int] = []
    firma: FirmaMedico | None = None
    pagina_firma: int | None = None

    seccion_actual: str | None = None
    seccion_padre: str | None = None
    pagina_inicio_seccion: int | None = None
    buffer_texto: list[str] = []
    candidato_nombre_firma: str | None = None

    pagina_actual = 1

    def cerrar_seccion_texto() -> None:
        if seccion_actual is not None and seccion_actual != _SECCION_MEDIDAS and buffer_texto:
            secciones.append(
                SeccionTextoEco(nombre=seccion_actual, texto=" ".join(buffer_texto).strip())
            )
            paginas_secciones.append(pagina_inicio_seccion or pagina_actual)
        buffer_texto.clear()

    for pagina_actual, pagina in enumerate(paginas, start=1):
        for linea in pagina.splitlines():
            linea_limpia = linea.strip()
            if not linea_limpia:
                continue
            if es_boilerplate_eco(linea_limpia):
                continue

            # Formato legado: etiqueta explícita "Firma: Nombre - MP123".
            coincidencia_firma = _PATRON_FIRMA.search(linea_limpia)
            if coincidencia_firma:
                cerrar_seccion_texto()
                firma = FirmaMedico(
                    nombre=coincidencia_firma.group("nombre").strip(),
                    matricula=coincidencia_firma.group("matricula").strip(),
                )
                pagina_firma = pagina_actual
                seccion_actual = None
                seccion_padre = None
                candidato_nombre_firma = None
                continue

            candidata = linea_limpia.upper()
            candidata_normalizada = candidata.rstrip(":").strip()

            # Fix #6 (trigger de MEDIDAS, ver `sdd/pdf-pii-anonymization/apply-progress`): el
            # documento real nunca trae "MEDIDAS" a secas, sólo el encabezado repetido
            # "MEDIDAS VALOR VALOR NORMAL ...". Trigger: cualquier línea cuyo primer token sea "MEDIDAS".
            es_trigger_medidas = candidata_normalizada == _SECCION_MEDIDAS or (
                candidata_normalizada.startswith(f"{_SECCION_MEDIDAS} ")
            )
            if es_trigger_medidas or candidata_normalizada in _SECCIONES_TEXTO:
                cerrar_seccion_texto()
                seccion_actual = _SECCION_MEDIDAS if es_trigger_medidas else candidata_normalizada
                seccion_padre = None if es_trigger_medidas else candidata_normalizada
                pagina_inicio_seccion = pagina_actual
                continue

            if seccion_padre is not None and candidata_normalizada in _SUBSECCIONES.get(
                seccion_padre, ()
            ):
                cerrar_seccion_texto()
                seccion_actual = f"{seccion_padre} - {candidata_normalizada}"
                pagina_inicio_seccion = pagina_actual
                continue

            # Formato real: línea de matrícula, chequeada antes de decidir si es texto de sección.
            coincidencia_matricula = _PATRON_MATRICULA.search(linea_limpia)
            if coincidencia_matricula:
                cerrar_seccion_texto()
                if candidato_nombre_firma is not None:
                    letra = coincidencia_matricula.group(1).upper()
                    numero = coincidencia_matricula.group(2)
                    firma = FirmaMedico(
                        nombre=candidato_nombre_firma, matricula=f"{letra} {numero}"
                    )
                    pagina_firma = pagina_actual
                seccion_actual = None
                seccion_padre = None
                candidato_nombre_firma = None
                continue

            # Guardado explícito: una fila de medidas sin dígitos (p. ej. "VD NORMAL")
            # matchearía como línea "nombre-like" si se chequeara dentro de la tabla de medidas.
            if (
                seccion_actual != _SECCION_MEDIDAS
                and candidata not in _TEXTO_FIRMA_EXCLUIDO
                and _PATRON_NOMBRE_FIRMA.fullmatch(linea_limpia)
            ):
                candidato_nombre_firma = linea_limpia
                continue

            if seccion_actual == _SECCION_MEDIDAS:
                if candidata.startswith("MEDIDAS") and "VALOR" in candidata:
                    continue  # encabezado repetido de la tabla, no es una fila de datos
                if "|" in linea_limpia:
                    partes = [parte.strip() for parte in linea_limpia.split("|")]
                    if len(partes) < 2:
                        continue
                    unidad = partes[2] if len(partes) > 2 and partes[2] else None
                    medidas.append(MedidaEco(nombre=partes[0], valor=partes[1], unidad=unidad))
                    paginas_medidas.append(pagina_actual)
                else:
                    medidas_linea = _parsear_fila_medidas_dos_columnas(linea_limpia)
                    medidas.extend(medidas_linea)
                    paginas_medidas.extend([pagina_actual] * len(medidas_linea))
            elif seccion_actual is not None:
                buffer_texto.append(linea_limpia)

    cerrar_seccion_texto()
    return _CuerpoEco(
        tuple(medidas), tuple(paginas_medidas), tuple(secciones), tuple(paginas_secciones), firma, pagina_firma
    )


class ParseadorEcoDoppler:
    """Parser del layout de ecocardiograma Doppler."""

    tipo_documento = TipoDocumento.ECOCARDIOGRAMA

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        texto_completo = texto.texto_completo_ordenado
        header = _buscar_campos(texto_completo, _CAMPOS_HEADER)

        # Dos chequeos separados: ver `dominio/errores.py::DetalleParseoIncompleto`.
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

        try:
            fecha_estudio = _parsear_fecha(header["fecha"])
        except ValueError as _exc:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
                etapa=_ETAPA,
                detalle_parseo=DetalleParseoIncompleto.FECHA_ILEGIBLE,
            ) from _exc

        identidad = IdentidadCruda(
            nombre=SecretStr(header["nombre"]),
            dni=SecretStr(header["dni"]) if header.get("dni") else None,
            fecha_nac=None,  # el eco no trae fecha de nacimiento en el header (ver spec)
            ids_internos=(
                (SecretStr(header["numero_estudio"]),)
                if header.get("numero_estudio")
                else ()
            ),
        )

        adicionales = {
            clave: valor
            for clave, valor in header.items()
            if clave not in ("nombre", "dni", "fecha", "numero_estudio")
        }

        cuerpo = _parsear_cuerpo(texto.paginas_ordenadas)
        medidas, secciones_texto, firma = cuerpo.medidas, cuerpo.secciones, cuerpo.firma

        # El eco nunca trae hora: hora_estudio/precision_hora quedan en sus defaults
        # (None/AUSENTE), sin declarar ReferenciaCampo de hora.
        contenido = ContenidoEco(medidas=medidas, secciones_texto=secciones_texto, firma=firma)
        fuentes = (
            ReferenciaCampo("eco.nombre", 1, "eco.nombre"),
            ReferenciaCampo("eco.fecha_estudio", 1, "eco.fecha_estudio"),
            *((ReferenciaCampo("eco.numero_estudio", 1, "eco.numero_estudio"),) if identidad.ids_internos else ()),
            *((ReferenciaCampo("eco.dni", 1, "eco.dni"),) if identidad.dni else ()),
            *((ReferenciaCampo("eco.firma", cuerpo.pagina_firma or 1, "eco.firma"),) if contenido.firma else ()),
        ) + (
            tuple(
                ReferenciaCampo("eco.medida", cuerpo.paginas_medidas[ordinal], selector_medida_eco(medida.nombre), ordinal)
                for ordinal, medida in enumerate(contenido.medidas)
            )
            + tuple(
                ReferenciaCampo("eco.seccion", cuerpo.paginas_secciones[ordinal], "eco.seccion", ordinal)
                for ordinal, seccion in enumerate(contenido.secciones_texto)
            )
        )

        return DocumentoParseado(
            tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
            version_esquema=_VERSION_ESQUEMA,
            identidad=identidad,
            fecha_estudio=fecha_estudio,
            contenido=contenido,
            adicionales=adicionales,
            fuentes=fuentes,
        )
