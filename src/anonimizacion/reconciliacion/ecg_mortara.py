"""Strategy de reconciliación para ECG Mortara."""

from __future__ import annotations

from datetime import datetime

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ContenidoEcg

from ._comun import reconciliar_referencias


class ReconciliadorEcgMortara:
    tipo_documento = TipoDocumento.ECG

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
