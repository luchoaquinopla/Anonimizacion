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


_PATRONES_INVENTARIO = (
    ("ecg.nombre", "header", re.compile(r"(?m)^[^\n~]+~,")),
    ("ecg.id_estudio", "header", re.compile(r"ID:\S+")),
    ("ecg.fecha_estudio", "header", re.compile(r"\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2}")),
    ("ecg.fecha_nacimiento", "header", re.compile(r"(?m)^\d{2}-[A-Za-z]{3}-\d{4}\s*\(\d+\s*yr\)")),
    ("ecg.vent_rate", "medida", re.compile(r"\bVent\.?\s*[Rr]ate\b")),
    ("ecg.pr_interval", "medida", re.compile(r"\bPR(?:\s*interval)?\b")),
    ("ecg.qrs_duration", "medida", re.compile(r"\bQRS(?:\s*duration)?\b")),
    ("ecg.qt_qtc", "medida", re.compile(r"\bQT/QTc\b")),
    ("ecg.ejes", "medida", re.compile(r"\bP-R-T\s*(?:axes)?\b")),
)

# Boilerplate fijo del fabricante; se consulta en memoria y nunca se persiste.
_WHITELIST_ECG = frozenset({"pid / name mismatch"})


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
            ("ecg.fecha_nacimiento", 0): fecha_nacimiento,
            ("ecg.vent_rate", 0): contenido.vent_rate,
            ("ecg.pr_interval", 0): contenido.pr_interval,
            ("ecg.qrs_duration", 0): contenido.qrs_duration,
            ("ecg.qt_qtc", 0): contenido.qt_qtc,
            ("ecg.ejes", 0): contenido.ejes,
        }
        reconciliar_referencias(documento, texto, {clave: valor for clave, valor in valores.items() if valor is not None})
        reconciliar_cobertura(documento, self.inventariar(texto))
