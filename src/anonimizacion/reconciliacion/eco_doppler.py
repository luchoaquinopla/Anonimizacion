"""Strategy de reconciliación para ecocardiograma Doppler."""

from __future__ import annotations

import re

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo, EtapaDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.eco_doppler import ContenidoEco
from anonimizacion.dominio.referencias import selector_medida_eco

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
_PATRON_NOMBRE_FIRMA = re.compile(r"^[A-ZÁÉÍÓÚÑ.]+(?:\s+[A-ZÁÉÍÓÚÑ.]+)+$")
_PATRON_MEDIDA_PIPE = re.compile(r"^[A-ZÁÉÍÓÚÑ.][A-ZÁÉÍÓÚÑ. ]*\|\s*[^|]+\|\s*.*$", re.IGNORECASE)
_PATRON_MEDIDA_SIMPLE = re.compile(r"^[A-ZÁÉÍÓÚÑ.][A-ZÁÉÍÓÚÑ. ]*\s+-?[\d.,]+(?:\s*\S+)?$", re.IGNORECASE)
_WHITELIST_ECO = frozenset({"diagnostico por imagenes"})


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


def _asociacion_eco(referencia: object, esperado: str, pagina: str) -> bool:
    """Exige que el selector eco y su valor compartan la misma estructura."""
    selector = getattr(referencia, "selector")
    patrones_header = {
        "eco.nombre": r"paciente:\s*(.+)",
        "eco.dni": r"documento:\s*(.+)",
        "eco.numero_estudio": r"n[ºo°]\s*estudio:\s*(.+)",
        "eco.fecha_estudio": r"fecha estudio:\s*(\d{1,2}/\d{1,2}/\d{4})",
    }
    patron_header = patrones_header.get(selector)
    if patron_header is not None:
        coincidencia = re.search(patron_header, pagina, re.IGNORECASE)
        return coincidencia is not None and normalizar_texto(coincidencia.group(1)).replace(",", ".") == esperado
    if selector.startswith("eco.medida."):
        partes = esperado.split()
        corte = next(
            (
                indice
                for indice in range(1, len(partes))
                if selector_medida_eco(" ".join(partes[:indice])) == selector
            ),
            None,
        )
        if corte is None:
            return False
        etiqueta = " ".join(partes[:corte])
        valor_esperado = " ".join(partes[corte:])
        for linea_original in pagina.splitlines():
            linea = normalizar_texto(linea_original).replace(",", ".")
            if "|" in linea:
                candidata = " ".join(parte.strip() for parte in linea.split("|") if parte.strip())
                if candidata == esperado:
                    return True
                continue
            if re.search(rf"(?:^|\s){re.escape(etiqueta)}\s+{re.escape(valor_esperado)}(?!\w)", linea):
                return True
        return False
    if selector == "eco.seccion":
        nombre, _, contenido = esperado.partition(" ")
        pagina_normalizada = normalizar_texto(pagina).replace(",", ".")
        return bool(contenido and re.search(rf"(?<!\w){re.escape(nombre)}\s+{re.escape(contenido)}(?!\w)", pagina_normalizada))
    if selector == "eco.firma":
        return esperado in normalizar_texto(pagina).replace(",", ".")
    return False


def _normalizar_matricula(matricula: str) -> str:
    """Equivale la abreviatura MP del formato legado, sin alterar matrículas."""
    normalizada = normalizar_texto(matricula)
    return re.sub(r"^mp\s*", "", normalizada)


def _firma_anclada(pagina: str, nombre: str, matricula: str) -> bool:
    """Verifica una única estructura de firma, no tokens dispersos en la página."""
    nombre_esperado = normalizar_texto(nombre)
    matricula_esperada = _normalizar_matricula(matricula)
    lineas = [linea.strip() for linea in pagina.splitlines() if linea.strip()]

    for indice, linea in enumerate(lineas):
        coincidencia = re.fullmatch(r"firma:\s*(.+?)\s*-\s*(.+)", linea, re.IGNORECASE)
        if coincidencia is not None:
            if (
                normalizar_texto(coincidencia.group(1)) == nombre_esperado
                and _normalizar_matricula(coincidencia.group(2)) == matricula_esperada
            ):
                return True
        coincidencia = re.fullmatch(r"(.+?)\s+mp\s+(\S+)", linea, re.IGNORECASE)
        if coincidencia is not None:
            if (
                normalizar_texto(coincidencia.group(1)) == nombre_esperado
                and _normalizar_matricula(f"MP {coincidencia.group(2)}") == matricula_esperada
            ):
                return True
        coincidencia = re.fullmatch(r"matr[ií]cula\s+([a-z])\s*(\d+)", linea, re.IGNORECASE)
        if coincidencia is not None:
            matricula_real = f"{coincidencia.group(1)} {coincidencia.group(2)}"
            if _normalizar_matricula(matricula_real) != matricula_esperada:
                continue
            for candidata in reversed(lineas[:indice]):
                if (
                    re.fullmatch(r"firma:\s*.+", candidata, re.IGNORECASE)
                    or _PATRON_FIRMA_LEGADA.fullmatch(candidata)
                    or re.fullmatch(r"matr[ií]cula\s+.+", candidata, re.IGNORECASE)
                ):
                    break
                if normalizar_texto(candidata) == nombre_esperado:
                    return True
                if _PATRON_NOMBRE_FIRMA.fullmatch(candidata):
                    return False
    return False


class ReconciliadorEcoDoppler:
    tipo_documento = TipoDocumento.ECOCARDIOGRAMA

    def es_texto_permitido(self, texto: str) -> bool:
        """Reconoce boilerplate Eco declarado, sin convertirlo en dato clínico."""
        return normalizar_texto(texto) in _WHITELIST_ECO

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
                if self.es_texto_permitido(linea):
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
                pagina = texto.paginas_ordenadas[referencia.pagina - 1]
                if not _firma_anclada(pagina, contenido.firma.nombre, contenido.firma.matricula):
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
        reconciliar_referencias(documento, texto, valores, validador_asociacion=_asociacion_eco)
        reconciliar_cobertura(documento, self.inventariar(texto))
