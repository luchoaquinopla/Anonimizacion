"""Strategy de reconciliación para ECG Mortara."""

from __future__ import annotations

from datetime import datetime
import re

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ContenidoEcg

from ._comun import reconciliar_cobertura, reconciliar_referencias
from .base import HallazgoCobertura
from .normalizacion import normalizar_texto


_PATRON_TIMESTAMP_COMPLETO = re.compile(r"\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2}")

_PATRONES_INVENTARIO = (
    ("ecg.nombre", "header", re.compile(r"(?m)^[^\n~]+~,")),
    ("ecg.id_estudio", "header", re.compile(r"ID:\S+")),
    ("ecg.fecha_estudio", "header", _PATRON_TIMESTAMP_COMPLETO),
    # Gotcha 1 (design.md, decisión 4): NO usar un patrón suelto
    # `\d{2}:\d{2}:\d{2}` -- matchearía cualquier otra hora del documento
    # (p. ej. una hora de impresión) y produciría `COBERTURA_AMBIGUA`. Se
    # reutiliza el mismo patrón del timestamp completo que `ecg.fecha_estudio`
    # (anclado a `DD-MON-YYYY HH:MM:SS`) para identificar sin ambigüedad la
    # hora del estudio.
    ("ecg.hora_estudio", "header", _PATRON_TIMESTAMP_COMPLETO),
    ("ecg.fecha_nacimiento", "header", re.compile(r"(?m)^\d{2}-[A-Za-z]{3}-\d{4}\s*\(\d+\s*yr\)")),
    ("ecg.vent_rate", "medida", re.compile(r"\bVent\.?\s*[Rr]ate\b")),
    ("ecg.pr_interval", "medida", re.compile(r"\bPR(?:\s*interval)?\b")),
    ("ecg.qrs_duration", "medida", re.compile(r"\bQRS(?:\s*duration)?\b")),
    ("ecg.qt_qtc", "medida", re.compile(r"\bQT/QTc\b")),
    ("ecg.ejes", "medida", re.compile(r"\bP-R-T\s*(?:axes)?\b")),
)

# Boilerplate fijo del fabricante; se consulta en memoria y nunca se persiste.
_WHITELIST_ECG = frozenset({"pid / name mismatch"})

_PATRONES_ASOCIACION = {
    "ecg.vent_rate": re.compile(r"\bVent\.?\s*[Rr]ate\b\s*:?\s*(.*)"),
    "ecg.pr_interval": re.compile(r"\bPR(?:\s*interval)?\b\s*:?\s*(.*)"),
    "ecg.qrs_duration": re.compile(r"\bQRS(?:\s*duration)?\b\s*:?\s*(.*)"),
    "ecg.qt_qtc": re.compile(r"\bQT/QTc\b\s*:?\s*(.*)"),
}


def _igual(valor: str, esperado: str) -> bool:
    return normalizar_texto(valor).replace(",", ".") == esperado


def _valor_cercano(lineas: list[str], indice: int) -> str | None:
    for desplazamiento in (-1, 1, -2, 2, -3, 3):
        candidata = indice + desplazamiento
        if 0 <= candidata < len(lineas):
            valor = normalizar_texto(lineas[candidata]).replace(",", ".")
            if re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:/[+-]?\d+(?:\.\d+)?)?", valor):
                return valor
    return None


def _asociacion_ecg(referencia: object, esperado: str, pagina: str) -> bool:  # noqa: C901 -- deuda conocida, ver pyproject.toml
    """Comprueba que el selector ECG ancle el valor a su etiqueta real."""
    selector = getattr(referencia, "selector")
    if selector == "ecg.nombre":
        coincidencia = re.search(r"(?m)^([^\n~]+)~,", pagina)
        return coincidencia is not None and _igual(coincidencia.group(1), esperado)
    if selector == "ecg.id_estudio":
        coincidencia = re.search(r"\bid:\s*(\S+)", pagina, re.IGNORECASE)
        return coincidencia is not None and _igual(coincidencia.group(1), esperado)
    if selector == "ecg.fecha_estudio":
        coincidencia = re.search(r"\b(\d{2}-[a-z]{3}-\d{4})\s+\d{2}:\d{2}:\d{2}", pagina, re.IGNORECASE)
        return coincidencia is not None and _igual(coincidencia.group(1), esperado)
    if selector == "ecg.hora_estudio":
        # Misma ancla que `ecg.fecha_estudio`: solo cuenta la hora que sigue
        # inmediatamente a una fecha `DD-MON-YYYY` (el timestamp completo del
        # estudio), nunca una hora suelta en otra parte del documento.
        coincidencia = re.search(r"\b\d{2}-[a-z]{3}-\d{4}\s+(\d{2}:\d{2}:\d{2})", pagina, re.IGNORECASE)
        return coincidencia is not None and _igual(coincidencia.group(1), esperado)
    if selector == "ecg.fecha_nacimiento":
        coincidencia = re.search(r"(?m)^(\d{2}-[a-z]{3}-\d{4})\s*\(\d+\s*yr\)", pagina, re.IGNORECASE)
        return coincidencia is not None and _igual(coincidencia.group(1), esperado)
    if selector == "ecg.ejes":
        lineas = pagina.splitlines()
        for indice, linea in enumerate(lineas):
            coincidencia = re.search(r"\bp-r-t\s*(?:axes)?\b\s*:?\s*(.*)", linea, re.IGNORECASE)
            if coincidencia:
                resto = normalizar_texto(coincidencia.group(1)).replace(",", ".")
                if resto and re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:\s+[+-]?\d+(?:\.\d+)?){1,2}", resto):
                    if _igual(resto, esperado):
                        return True
                valores: list[str] = []
                cursor = indice - 1
                while cursor >= 0 and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", lineas[cursor].strip()):
                    valores.append(lineas[cursor].strip())
                    cursor -= 1
                if valores and _igual(" ".join(reversed(valores[:3])), esperado):
                    return True
                valores = []
                cursor = indice + 1
                while cursor < len(lineas) and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", lineas[cursor].strip()):
                    valores.append(lineas[cursor].strip())
                    cursor += 1
                if valores and _igual(" ".join(valores[:3]), esperado):
                    return True
        return False
    patron = _PATRONES_ASOCIACION.get(selector)
    if patron is None:
        return False
    for indice, linea in enumerate(pagina.splitlines()):
        coincidencia = patron.search(linea)
        if coincidencia is None:
            continue
        resto = normalizar_texto(coincidencia.group(1)).replace(",", ".")
        candidato = resto if resto and re.search(r"\d", resto) else _valor_cercano(pagina.splitlines(), indice)
        if candidato is not None and _igual(candidato, esperado):
            return True
    return False


class ReconciliadorEcgMortara:
    tipo_documento = TipoDocumento.ECG

    def es_texto_permitido(self, texto: str) -> bool:
        """Reconoce únicamente boilerplate ECG declarado, sin conservarlo."""
        return texto.strip().casefold() in _WHITELIST_ECG

    def inventariar(self, texto: TextoExtraido) -> tuple[HallazgoCobertura, ...]:
        """Reconoce headers y medidas ECG sin consultar el documento parseado."""
        hallazgos: list[HallazgoCobertura] = []
        for id_campo, clase, patron in _PATRONES_INVENTARIO:
            for pagina, contenido in enumerate(texto.paginas, start=1):
                for _coincidencia in patron.finditer(contenido):
                    hallazgos.append(HallazgoCobertura(id_campo, pagina, clase=clase))
        return tuple(hallazgos)

    def reconciliar(self, documento: DocumentoParseado, texto: TextoExtraido) -> None:
        contenido = documento.contenido
        if not isinstance(contenido, ContenidoEcg):
            raise TypeError("contenido ECG inválido")
        fecha_nacimiento = (
            datetime.strptime(documento.identidad.fecha_nac.get_secret_value(), "%Y-%m-%d").strftime("%d-%b-%Y")
            if documento.identidad.fecha_nac
            else None
        )
        valores = {
            ("ecg.nombre", 0): documento.identidad.nombre.get_secret_value(),
            **({("ecg.id_estudio", 0): documento.identidad.ids_internos[0].get_secret_value()} if documento.identidad.ids_internos else {}),
            ("ecg.fecha_estudio", 0): documento.fecha_estudio.strftime("%d-%b-%Y"),
            ("ecg.hora_estudio", 0): (
                documento.hora_estudio.strftime("%H:%M:%S") if documento.hora_estudio is not None else None
            ),
            ("ecg.fecha_nacimiento", 0): fecha_nacimiento,
            ("ecg.vent_rate", 0): contenido.vent_rate,
            ("ecg.pr_interval", 0): contenido.pr_interval,
            ("ecg.qrs_duration", 0): contenido.qrs_duration,
            ("ecg.qt_qtc", 0): contenido.qt_qtc,
            ("ecg.ejes", 0): contenido.ejes,
        }
        reconciliar_referencias(
            documento,
            texto,
            {clave: valor for clave, valor in valores.items() if valor is not None},
            validador_asociacion=_asociacion_ecg,
        )
        reconciliar_cobertura(documento, self.inventariar(texto))
