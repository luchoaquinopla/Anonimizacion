"""Registro Strategy de reconciliadores por tipo documental."""

from __future__ import annotations

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import ReconciliadorDocumento
from .ecg_mortara import ReconciliadorEcgMortara
from .eco_doppler import ReconciliadorEcoDoppler
from .laboratorio_general import ReconciliadorLaboratorioGeneral

_REGISTRO: dict[TipoDocumento, ReconciliadorDocumento] = {
    TipoDocumento.ECG: ReconciliadorEcgMortara(),
    TipoDocumento.LABORATORIO: ReconciliadorLaboratorioGeneral(),
    TipoDocumento.ECOCARDIOGRAMA: ReconciliadorEcoDoppler(),
}


def obtener_reconciliador(tipo: TipoDocumento) -> ReconciliadorDocumento:
    """Devuelve la Strategy registrada o falla sin exponer contenido."""
    reconciliador = _REGISTRO.get(tipo)
    if reconciliador is None:
        raise ErrorParseo(CodigoErrorDocumento.TIPO_NO_RECONOCIDO, "reconciliacion")
    return reconciliador
