"""Operaciones internas y puras para Strategies de reconciliación."""

from __future__ import annotations

from collections.abc import Mapping

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo, EtapaDocumento
from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

from .normalizacion import normalizar_texto


def reconciliar_referencias(
    documento: DocumentoParseado, texto: TextoExtraido, valores: Mapping[tuple[str, int], str]
) -> None:
    """Verifica una evidencia por referencia sin conservar su contenido."""
    referencias_vistas: set[tuple[str, int]] = set()
    for referencia in documento.fuentes:
        clave = (referencia.id_campo, referencia.ordinal)
        if clave in referencias_vistas or clave not in valores:
            raise ErrorParseo(CodigoErrorDocumento.EVIDENCIA_AUSENTE, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        referencias_vistas.add(clave)
        if referencia.pagina > len(texto.paginas):
            raise ErrorParseo(CodigoErrorDocumento.EVIDENCIA_AUSENTE, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        valor = normalizar_texto(valores[clave]).replace(",", ".")
        paginas = texto.paginas if documento.tipo_documento is TipoDocumento.ECG else texto.paginas_ordenadas
        pagina = normalizar_texto(paginas[referencia.pagina - 1]).replace(",", ".")
        ocurrencias = pagina.count(valor)
        if ocurrencias == 1:
            continue
        codigo = CodigoErrorDocumento.EVIDENCIA_AMBIGUA if ocurrencias > 1 else CodigoErrorDocumento.VALOR_DISCREPANTE
        if not any(caracter.isdigit() for caracter in pagina):
            codigo = CodigoErrorDocumento.EVIDENCIA_AUSENTE
        raise ErrorParseo(codigo, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
