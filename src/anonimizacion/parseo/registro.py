"""Registro `TipoDocumento -> ParseadorDocumento`.
Agregar un layout nuevo es una entrada más en `_REGISTRO`, no un cambio en el ejecutor."""

from __future__ import annotations

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import ParseadorDocumento
from .ecg_mortara import ParseadorEcgMortara
from .eco_doppler import ParseadorEcoDoppler
from .laboratorio_general import ParseadorLaboratorioGeneral

_ETAPA = "parseo"

_REGISTRO: dict[TipoDocumento, ParseadorDocumento] = {
    TipoDocumento.LABORATORIO: ParseadorLaboratorioGeneral(),
    TipoDocumento.ECG: ParseadorEcgMortara(),
    TipoDocumento.ECOCARDIOGRAMA: ParseadorEcoDoppler(),
}


def obtener_parseador(tipo: TipoDocumento) -> ParseadorDocumento:
    """Devuelve el parser registrado para `tipo`.
    Lanza `ErrorParseo(TIPO_NO_RECONOCIDO)` si no hay parser registrado."""
    parseador = _REGISTRO.get(tipo)
    if parseador is None:
        raise ErrorParseo(codigo=CodigoErrorDocumento.TIPO_NO_RECONOCIDO, etapa=_ETAPA)
    return parseador
