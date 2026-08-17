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

Fix post-PR9 #4 (recalibración lab/eco contra 3 documentos reales, ver
`sdd/pdf-pii-anonymization/apply-progress`): el header real usa `PACIENTE:`
(mayúsculas) y `Fecha Estudio:` (nunca `Fecha:` a secas); el cuerpo real
trae las medidas en una tabla de dos sub-columnas separadas por 2+ espacios
(no `|`, ver `_parsear_fila_medidas_dos_columnas`) y secciones de texto
anidadas en dos niveles (ver `_SUBSECCIONES`); la firma del médico
informante no trae la etiqueta "Firma:" -- se detecta con una heurística de
"última línea nombre-like antes de la línea de Matrícula" (ver
`_PATRON_MATRICULA`/`_PATRON_NOMBRE_FIRMA`). Todo esto calibrado contra una
sola muestra real de cada tipo de documento -- ver comentarios puntuales en
cada función para el detalle de qué podría no generalizar.
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
    "VALVULAS CARDIACAS",
    "AURICULAS",
    "PERICARDIO",
    "EVALUACION DE FLUJOS POR DOPPLER",
    "CONCLUSIONES",
)
_SECCION_MEDIDAS = "MEDIDAS"

# Fix post-PR9 #4 (recalibración lab/eco contra 3 documentos reales, ver
# `sdd/pdf-pii-anonymization/apply-progress`): el documento real anida
# subsecciones dentro de algunas secciones de texto libre (p. ej. "AORTICA"
# dentro de "VALVULAS CARDIACAS"). `SeccionTextoEco` es un modelo plano
# (nombre + texto), sin jerarquía nativa -- en vez de cambiar ese modelo
# (rompería el contrato ya consumido por `salida/constructor_registro.py`),
# cada subsección se representa como su propia `SeccionTextoEco` con nombre
# compuesto `"padre - hija"`. Calibrado contra una sola muestra: la lista de
# subsecciones esperadas por sección padre podría no cubrir variantes no
# vistas (otro orden, subsecciones adicionales, etc.).
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
    # Capturado como fecha estricta (no `.+`): en el documento real, "Fecha
    # Estudio:" comparte fila con el campo "PACIENTE:" separado por un solo
    # espacio (no el separador de 2+ espacios que `_primer_segmento` asume
    # para columnas), así que un `.+` genérico arrastraría el nombre del
    # paciente como parte de la fecha. Calibrado contra una sola muestra.
    "fecha": r"Fecha Estudio:\s*(\d{1,2}/\d{1,2}/\d{4})",
    "edad": r"Edad:\s*(.+)",
    "medico_solicitante": r"M[eé]dico Solicitante:\s*(.+)",
    "peso": r"Peso:\s*(.+)",
    "altura": r"Altura:\s*(.+)",
    "superficie_corporal": r"S\.C\.\s*:?\s*(.+)",
}

_PATRON_FIRMA = re.compile(r"Firma:\s*(?P<nombre>.+?)\s*-\s*MP\s*(?P<matricula>\S+)")

# Fix post-PR9 #4: el documento real NO trae la etiqueta "Firma:" en ningún
# lado. El nombre del médico informante aparece en una línea propia (todo
# en mayúsculas, sin etiqueta) y, en una línea posterior no necesariamente
# adyacente, aparece "Matrícula <letra> <número>" (p. ej. "Matrícula W
# 6707", con una letra de prefijo en vez de "MP"). Heurística: se recuerda
# la última línea "nombre-like" vista (todo mayúsculas, 2+ palabras, solo
# letras/espacios/puntos) y, al encontrar la línea de matrícula, se arma la
# firma con ese candidato. Si nunca hubo un candidato antes de la línea de
# matrícula, `firma` queda en `None` -- una firma mal parseada podría
# pseudonimizar al médico equivocado, así que se prioriza "no encontrar"
# sobre "encontrar mal". Calibrado contra una sola muestra real; podría no
# generalizar si el nombre y la matrícula aparecen en otro orden, o si hay
# líneas nombre-like intermedias no relacionadas (p. ej. el título del
# estudio) que pisen el candidato correcto.
_PATRON_MATRICULA = re.compile(r"Matr[ií]cula\s+([A-Za-z])\s*(\d+)", re.IGNORECASE)
_PATRON_NOMBRE_FIRMA = re.compile(r"^[A-ZÁÉÍÓÚÑ.]+(?:\s+[A-ZÁÉÍÓÚÑ.]+)+$")
_TEXTO_FIRMA_EXCLUIDO = {"DIAGNOSTICO POR IMAGENES"}


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


def _es_nombre_de_medida(token: str) -> bool:
    """Un token de la tabla de medidas real que parece nombre de medida.

    Solo letras/puntos (p. ej. "SEPTUM", "P.POSTERIOR"), sin dígitos. Excluye
    explícitamente "NORMAL"/"VARIABLE": son valores/rangos de referencia
    reales del documento, no nombres de medida, aunque también sean
    alfabéticos en mayúsculas.
    """
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
    """Parsea una fila de la tabla real de medidas: dos sub-columnas
    (izquierda/derecha) separadas por 2+ espacios, cada una con
    nombre + valor + rango de referencia opcional. El rango de referencia
    (p. ej. "< 41 mm", "VARIABLE") se descarta explícitamente: no hay campo
    en `MedidaEco` para guardarlo y no participa de ningún cálculo aguas
    abajo. Calibrado contra una sola muestra real -- el separador de columna
    (`\\s{2,}`, misma convención que `_primer_segmento`) y la heurística
    nombre/valor/rango podrían no generalizar a layouts con más sub-columnas
    o un orden distinto de campos.
    """
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


def _parsear_cuerpo(
    paginas: tuple[str, ...],
) -> tuple[tuple[MedidaEco, ...], tuple[SeccionTextoEco, ...], FirmaMedico | None]:
    medidas: list[MedidaEco] = []
    secciones: list[SeccionTextoEco] = []
    firma: FirmaMedico | None = None

    seccion_actual: str | None = None
    seccion_padre: str | None = None
    buffer_texto: list[str] = []
    candidato_nombre_firma: str | None = None

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

            # Formato legado (fixtures sintéticas anteriores a la
            # recalibración): etiqueta explícita "Firma: Nombre - MP123".
            coincidencia_firma = _PATRON_FIRMA.search(linea_limpia)
            if coincidencia_firma:
                cerrar_seccion_texto()
                firma = FirmaMedico(
                    nombre=coincidencia_firma.group("nombre").strip(),
                    matricula=coincidencia_firma.group("matricula").strip(),
                )
                seccion_actual = None
                seccion_padre = None
                candidato_nombre_firma = None
                continue

            candidata = linea_limpia.upper()
            candidata_normalizada = candidata.rstrip(":").strip()

            # Fix post-PR9 #6 (trigger de MEDIDAS, ver
            # `sdd/pdf-pii-anonymization/apply-progress`): el documento real
            # NUNCA trae una línea igual a "MEDIDAS" a secas -- la única
            # línea que marca el inicio de la tabla es el encabezado
            # repetido "MEDIDAS VALOR VALOR NORMAL MEDIDAS VALOR VALOR
            # NORMAL". Se reconoce como trigger cualquier línea cuyo primer
            # token sea "MEDIDAS" (no solo la igualdad exacta), sin afectar
            # el resto del manejo de estado (`_SECCION_MEDIDAS` sigue siendo
            # el nombre de la sección una vez identificada).
            es_trigger_medidas = candidata_normalizada == _SECCION_MEDIDAS or (
                candidata_normalizada.startswith(f"{_SECCION_MEDIDAS} ")
            )
            if es_trigger_medidas or candidata_normalizada in _SECCIONES_TEXTO:
                cerrar_seccion_texto()
                seccion_actual = _SECCION_MEDIDAS if es_trigger_medidas else candidata_normalizada
                seccion_padre = None if es_trigger_medidas else candidata_normalizada
                continue

            if seccion_padre is not None and candidata_normalizada in _SUBSECCIONES.get(
                seccion_padre, ()
            ):
                cerrar_seccion_texto()
                seccion_actual = f"{seccion_padre} - {candidata_normalizada}"
                continue

            # Formato real (sin etiqueta "Firma:"): línea de matrícula, en
            # cualquier punto del documento -- se chequea antes de decidir
            # si la línea es texto de sección para no arrastrar el nombre
            # del médico ni la línea de matrícula al buffer de la última
            # sección de texto conocida.
            coincidencia_matricula = _PATRON_MATRICULA.search(linea_limpia)
            if coincidencia_matricula:
                cerrar_seccion_texto()
                if candidato_nombre_firma is not None:
                    letra = coincidencia_matricula.group(1).upper()
                    numero = coincidencia_matricula.group(2)
                    firma = FirmaMedico(
                        nombre=candidato_nombre_firma, matricula=f"{letra} {numero}"
                    )
                seccion_actual = None
                seccion_padre = None
                candidato_nombre_firma = None
                continue

            # Guardado explícito por `seccion_actual != _SECCION_MEDIDAS`: una
            # fila de medidas real puede no tener dígitos (p. ej. "VD
            # NORMAL"), lo que la haría matchear como línea "nombre-like" si
            # se chequeara acá dentro de la tabla de medidas.
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
                else:
                    medidas.extend(_parsear_fila_medidas_dos_columnas(linea_limpia))
            elif seccion_actual is not None:
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
