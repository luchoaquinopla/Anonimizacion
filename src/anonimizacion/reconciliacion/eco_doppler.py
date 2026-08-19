"""Strategy de reconciliación para ecocardiograma Doppler."""

from __future__ import annotations

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo, EtapaDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.eco_doppler import ContenidoEco

from ._comun import reconciliar_referencias
from .normalizacion import normalizar_texto


class ReconciliadorEcoDoppler:
    tipo_documento = TipoDocumento.ECOCARDIOGRAMA

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
            **{("eco.seccion", indice): seccion.texto for indice, seccion in enumerate(contenido.secciones_texto)},
        }
        reconciliar_referencias(documento, texto, valores)
