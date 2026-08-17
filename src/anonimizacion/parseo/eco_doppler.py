"""Parser de ecocardiograma Doppler (spec `document-parsing`).

Mezcla dos tipos de contenido en el mismo documento: medidas estructuradas
(AO, AI, DDVI, DSVI, FA, Septum, P. Posterior, con su unidad) y texto libre
por sección (motilidad segmentaria, válvulas, pericardio, flujos Doppler,
conclusiones), más la firma del médico informante. El parser separa ambas
partes en campos distintos de `ContenidoEco` en vez de dejar todo como texto
plano, porque alimentan tablas distintas aguas abajo (Fase 7): las medidas
van a `medicion_eco` (tabla ancha), el texto libre a `texto_seccion_eco`.

Mismo formato de trabajo que `laboratorio_general.py`: filas de medida con
separador `|` (`nombre | valor | unidad`), pendiente de calibrar contra el
corpus real (ver design.md, "Pendientes").

Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
extracción con sort=True + firmas ECG reales"): mismo fix que
`laboratorio_general.py` -- el header se busca sobre
`texto.texto_completo_ordenado` (orden geométrico, `sort=True`), no
`texto.texto_completo` (orden de dibujado), y cada campo capturado se trunca
en el primer separador de 2+ espacios (`_primer_segmento`) para no arrastrar
un campo vecino que comparta la misma fila visual. El cuerpo (medidas +
texto libre + firma) se sigue parseando línea por línea sobre
`texto.paginas_ordenadas`, no `texto.paginas`, por la misma razón.
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

_SECCIONES_TEXTO = (
    "MOTILIDAD SEGMENTARIA",
    "VALVULAS",
    "PERICARDIO",
    "FLUJOS DOPPLER",
    "CONCLUSIONES",
)
_SECCION_MEDIDAS = "MEDIDAS"

_CAMPOS_HEADER = {
    "nombre": r"Paciente:\s*(.+)",
    "dni": r"Documento:\s*(.+)",
    "numero_estudio": r"N[ºo°]\s*Estudio:\s*(.+)",
    "fecha": r"Fecha:\s*(.+)",
    "medico_solicitante": r"M[eé]dico Solicitante:\s*(.+)",
    "peso": r"Peso:\s*(.+)",
    "altura": r"Altura:\s*(.+)",
    "superficie_corporal": r"S\.C\.:\s*(.+)",
}

_PATRON_FIRMA = re.compile(r"Firma:\s*(?P<nombre>.+?)\s*-\s*MP\s*(?P<matricula>\S+)")


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


def _primer_segmento(texto: str) -> str:
    """Trunca en el primer salto de 2+ espacios (separador de columnas del reporte).

    Misma convención que `parseo/ecg_mortara.py::_primer_segmento` y
    `parseo/laboratorio_general.py::_primer_segmento`: con `sort=True`, dos
    campos que comparten la misma fila visual pueden quedar en la misma
    línea del texto extraído.
    """
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


def _parsear_cuerpo(
    paginas: tuple[str, ...],
) -> tuple[tuple[MedidaEco, ...], tuple[SeccionTextoEco, ...], FirmaMedico | None]:
    medidas: list[MedidaEco] = []
    secciones: list[SeccionTextoEco] = []
    firma: FirmaMedico | None = None

    seccion_actual: str | None = None
    buffer_texto: list[str] = []

    def cerrar_seccion_texto() -> None:
        if seccion_actual is not None and seccion_actual != _SECCION_MEDIDAS and buffer_texto:
            secciones.append(
                SeccionTextoEco(nombre=seccion_actual, texto=" ".join(buffer_texto).strip())
            )
        buffer_texto.clear()

    for pagina in paginas:
        for linea in pagina.splitlines():
            linea_limpia = linea.strip()
            if not linea_limpia:
                continue

            coincidencia_firma = _PATRON_FIRMA.search(linea_limpia)
            if coincidencia_firma:
                cerrar_seccion_texto()
                firma = FirmaMedico(
                    nombre=coincidencia_firma.group("nombre").strip(),
                    matricula=coincidencia_firma.group("matricula").strip(),
                )
                seccion_actual = None
                continue

            candidata = linea_limpia.upper()
            if candidata == _SECCION_MEDIDAS or candidata in _SECCIONES_TEXTO:
                cerrar_seccion_texto()
                seccion_actual = candidata
                continue

            if seccion_actual == _SECCION_MEDIDAS:
                if "|" not in linea_limpia:
                    continue
                partes = [parte.strip() for parte in linea_limpia.split("|")]
                if len(partes) < 2:
                    continue
                unidad = partes[2] if len(partes) > 2 and partes[2] else None
                medidas.append(MedidaEco(nombre=partes[0], valor=partes[1], unidad=unidad))
            elif seccion_actual in _SECCIONES_TEXTO:
                buffer_texto.append(linea_limpia)

    cerrar_seccion_texto()
    return tuple(medidas), tuple(secciones), firma


class ParseadorEcoDoppler:
    """Parser del layout de ecocardiograma Doppler."""

    tipo_documento = TipoDocumento.ECOCARDIOGRAMA

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        texto_completo = texto.texto_completo_ordenado
        header = _buscar_campos(texto_completo, _CAMPOS_HEADER)

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

        medidas, secciones_texto, firma = _parsear_cuerpo(texto.paginas_ordenadas)

        contenido = ContenidoEco(medidas=medidas, secciones_texto=secciones_texto, firma=firma)

        return DocumentoParseado(
            tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
            version_esquema=_VERSION_ESQUEMA,
            identidad=identidad,
            fecha_estudio=fecha_estudio,
            contenido=contenido,
            adicionales=adicionales,
        )
