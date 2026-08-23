"""Operaciones internas y puras para Strategies de reconciliación."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping

from anonimizacion.dominio.errores import (
    CodigoErrorDocumento,
    ErrorParseo,
    EtapaDocumento,
)
from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

from .base import HallazgoCobertura, ReferenciaCampo
from .inventario import verificar_cobertura
from .normalizacion import normalizar_texto


def reconciliar_referencias(
    documento: DocumentoParseado,
    texto: TextoExtraido,
    valores: Mapping[tuple[str, int], str],
    *,
    ids_con_asociacion_estructurada: Collection[str] = (),
    validador_asociacion: Callable[[ReferenciaCampo, str, str], bool] | None = None,
) -> None:
    """Verifica evidencia simple y, si aplica, asociación selector→valor."""
    referencias_vistas: set[tuple[str, int]] = set()
    for referencia in documento.fuentes:
        if referencia.id_campo in ids_con_asociacion_estructurada:
            continue
        clave = (referencia.id_campo, referencia.ordinal)
        if clave in referencias_vistas or clave not in valores:
            raise ErrorParseo(CodigoErrorDocumento.EVIDENCIA_AUSENTE, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        referencias_vistas.add(clave)
        if referencia.pagina > len(texto.paginas):
            raise ErrorParseo(CodigoErrorDocumento.EVIDENCIA_AUSENTE, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        valor = normalizar_texto(valores[clave]).replace(",", ".")
        paginas = texto.paginas if documento.tipo_documento is TipoDocumento.ECG else texto.paginas_ordenadas
        pagina_original = paginas[referencia.pagina - 1]
        pagina = normalizar_texto(pagina_original).replace(",", ".")
        asociacion_valida = (
            validador_asociacion(referencia, valor, pagina_original)
            if validador_asociacion is not None
            else False
        )
        requiere_evidencia_compuesta = referencia.id_campo == "eco.seccion" or asociacion_valida
        ocurrencias = pagina.count(valor)
        if not requiere_evidencia_compuesta and ocurrencias != 1:
            codigo = CodigoErrorDocumento.EVIDENCIA_AMBIGUA if ocurrencias > 1 else CodigoErrorDocumento.VALOR_DISCREPANTE
            if not any(caracter.isdigit() for caracter in pagina):
                codigo = CodigoErrorDocumento.EVIDENCIA_AUSENTE
            raise ErrorParseo(codigo, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        if validador_asociacion is not None and not asociacion_valida:
            codigo = CodigoErrorDocumento.EVIDENCIA_AUSENTE if referencia.id_campo == "eco.seccion" else CodigoErrorDocumento.VALOR_DISCREPANTE
            raise ErrorParseo(codigo, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)


def reconciliar_cobertura(
    documento: DocumentoParseado, inventario: tuple[HallazgoCobertura, ...]
) -> None:
    """Comprueba PDF→modelo después de validar la evidencia modelo→PDF."""
    verificar_cobertura(inventario, documento.fuentes)
