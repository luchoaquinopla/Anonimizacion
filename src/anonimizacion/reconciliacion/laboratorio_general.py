"""Strategy de reconciliación para laboratorio general."""

from __future__ import annotations

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio

from ._comun import reconciliar_referencias


class ReconciliadorLaboratorioGeneral:
    tipo_documento = TipoDocumento.LABORATORIO

    def reconciliar(self, documento: DocumentoParseado, texto: TextoExtraido) -> None:
        contenido = documento.contenido
        if not isinstance(contenido, ContenidoLaboratorio):
            raise TypeError("contenido laboratorio inválido")
        valores = {("laboratorio.resultado", indice): fila.resultado for indice, fila in enumerate(contenido.resultados)}
        reconciliar_referencias(documento, texto, valores)
