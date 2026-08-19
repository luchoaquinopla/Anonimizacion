"""Strategy de reconciliación para ecocardiograma Doppler."""

from __future__ import annotations

import re

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo, EtapaDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.eco_doppler import ContenidoEco

from ._comun import reconciliar_cobertura, reconciliar_referencias
from .base import HallazgoCobertura
from .normalizacion import normalizar_texto


_CAMPOS_HEADER = {
    "eco.nombre": re.compile(r"(?i)paciente:\s*.+"),
    "eco.dni": re.compile(r"(?i)documento:\s*.+"),
    "eco.numero_estudio": re.compile(r"(?i)n[ºo°]\s*estudio:\s*.+"),
    "eco.fecha_estudio": re.compile(r"(?i)fecha estudio:\s*\d{1,2}/\d{1,2}/\d{4}"),
}
_SECCIONES = frozenset({
    "MOTILIDAD SEGMENTARIA",
    "VALVULAS CARDIACAS",
    "AURICULAS",
    "PERICARDIO",
    "EVALUACION DE FLUJOS POR DOPPLER",
    "CONCLUSIONES",
})
_SUBSECCIONES = frozenset({
    "AORTICA", "MITRAL", "PULMONAR", "TRICUSPIDEA", "IZQUIERDA", "DERECHA",
    "FLUJO AORTICO", "FLUJO MITRAL", "FLUJO PULMONAR", "FLUJO TRICUSPIDEO",
})
_PATRON_FIRMA = re.compile(r"(?i)^firma:\s*.+-\s*mp\s*\S+")
_PATRON_FIRMA_LEGADA = re.compile(r"(?i)^.+\s+mp\s+\S+$")
_PATRON_MATRICULA = re.compile(r"(?i)^matr[ií]cula\s+[a-z]\s*\d+")
_PATRON_MEDIDA_PIPE = re.compile(r"^[A-ZÁÉÍÓÚÑ.][A-ZÁÉÍÓÚÑ. ]*\|\s*[^|]+\|\s*.*$", re.IGNORECASE)
_PATRON_MEDIDA_SIMPLE = re.compile(r"^[A-ZÁÉÍÓÚÑ.][A-ZÁÉÍÓÚÑ. ]*\s+-?[\d.,]+(?:\s*\S+)?$", re.IGNORECASE)


def _normalizar_etiqueta(linea: str) -> str:
    return linea.strip().upper().rstrip(":").strip()


def _es_medida(linea: str) -> bool:
    return bool(_PATRON_MEDIDA_PIPE.fullmatch(linea) or _PATRON_MEDIDA_SIMPLE.fullmatch(linea))


def _es_nombre_medida(token: str) -> bool:
    etiqueta = token.strip().upper()
    return etiqueta not in {"NORMAL", "VARIABLE"} and bool(re.fullmatch(r"[A-ZÁÉÍÓÚÑ.]+", etiqueta))


def _cantidad_medidas_dos_columnas(linea: str) -> int:
    """Cuenta pares nombre-valor en la tabla real sin reutilizar el parser."""
    tokens = [token for token in re.split(r"\s{2,}", linea.strip()) if token]
    cantidad = 0
    indice = 0
    while indice < len(tokens):
        nombre = tokens[indice]
        indice += 1
        if not _es_nombre_medida(nombre) or indice >= len(tokens):
            continue
        indice += 1
        cantidad += 1
        if indice < len(tokens) and not _es_nombre_medida(tokens[indice]):
            indice += 1
    return cantidad


class ReconciliadorEcoDoppler:
    tipo_documento = TipoDocumento.ECOCARDIOGRAMA

    def inventariar(self, texto: TextoExtraido) -> tuple[HallazgoCobertura, ...]:
        """Reconoce destinos eco desde el PDF sin consultar el modelo parseado."""
        hallazgos: list[HallazgoCobertura] = []
        ordinal_medida = 0
        ordinal_seccion = 0
        en_medidas = False
        seccion_pendiente: tuple[int, bool] | None = None

        def cerrar_seccion() -> None:
            nonlocal seccion_pendiente, ordinal_seccion
            if seccion_pendiente is not None and seccion_pendiente[1]:
                hallazgos.append(HallazgoCobertura("eco.seccion", seccion_pendiente[0], ordinal_seccion, "seccion"))
                ordinal_seccion += 1
            seccion_pendiente = None

        for pagina_numero, pagina in enumerate(texto.paginas_ordenadas, start=1):
            for linea_cruda in pagina.splitlines():
                linea = linea_cruda.strip()
                if not linea:
                    continue
                for id_campo, patron in _CAMPOS_HEADER.items():
                    if patron.search(linea):
                        hallazgos.append(HallazgoCobertura(id_campo, pagina_numero, clase="header"))
                etiqueta = _normalizar_etiqueta(linea)
                if etiqueta == "MEDIDAS" or etiqueta.startswith("MEDIDAS "):
                    cerrar_seccion()
                    en_medidas = True
                    continue
                if etiqueta in _SECCIONES or etiqueta in _SUBSECCIONES:
                    cerrar_seccion()
                    en_medidas = False
                    seccion_pendiente = (pagina_numero, False)
                    continue
                if (
                    _PATRON_FIRMA.fullmatch(linea)
                    or _PATRON_FIRMA_LEGADA.fullmatch(linea)
                    or _PATRON_MATRICULA.fullmatch(linea)
                ):
                    cerrar_seccion()
                    en_medidas = False
                    hallazgos.append(HallazgoCobertura("eco.firma", pagina_numero, clase="dato"))
                    continue
                if en_medidas and "|" not in linea:
                    cantidad_medidas = _cantidad_medidas_dos_columnas(linea)
                    if cantidad_medidas == 0 and _es_medida(linea):
                        cantidad_medidas = 1
                else:
                    cantidad_medidas = int(("|" in linea or seccion_pendiente is None) and _es_medida(linea))
                if cantidad_medidas:
                    for _ in range(cantidad_medidas):
                        hallazgos.append(HallazgoCobertura("eco.medida", pagina_numero, ordinal_medida, "medida"))
                        ordinal_medida += 1
                    continue
                if seccion_pendiente is not None:
                    seccion_pendiente = (seccion_pendiente[0], True)
        cerrar_seccion()
        return tuple(hallazgos)

    def reconciliar(self, documento: DocumentoParseado, texto: TextoExtraido) -> None:
        contenido = documento.contenido
        if not isinstance(contenido, ContenidoEco):
            raise TypeError("contenido eco inválido")
        for referencia in documento.fuentes:
            if referencia.id_campo == "eco.firma" and contenido.firma:
                pagina = normalizar_texto(texto.paginas_ordenadas[referencia.pagina - 1])
                if normalizar_texto(contenido.firma.nombre) not in pagina or normalizar_texto(contenido.firma.matricula) not in pagina:
                    raise ErrorParseo(CodigoErrorDocumento.VALOR_DISCREPANTE, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        valores = {
            ("eco.nombre", 0): documento.identidad.nombre.get_secret_value(),
            ("eco.fecha_estudio", 0): documento.fecha_estudio.strftime("%d/%m/%Y"),
            **({("eco.dni", 0): documento.identidad.dni.get_secret_value()} if documento.identidad.dni else {}),
            **({("eco.numero_estudio", 0): documento.identidad.ids_internos[0].get_secret_value()} if documento.identidad.ids_internos else {}),
            **({("eco.firma", 0): contenido.firma.nombre} if contenido.firma else {}),
            **{("eco.medida", indice): f"{medida.nombre} {medida.valor}{(' ' + medida.unidad) if medida.unidad else ''}" for indice, medida in enumerate(contenido.medidas)},
            **{("eco.seccion", indice): f"{seccion.nombre} {seccion.texto}" for indice, seccion in enumerate(contenido.secciones_texto)},
        }
        reconciliar_referencias(documento, texto, valores)
        reconciliar_cobertura(documento, self.inventariar(texto))
