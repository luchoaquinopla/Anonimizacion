"""Tests del registro `TipoDocumento -> ParseadorDocumento` (spec: document-parsing).

Mismo patrón Strategy+registro que `deteccion/firmas` (Fase 3): un layout
nuevo es una entrada más acá, no un cambio en el ejecutor del pipeline.
"""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.ecg_mortara import ParseadorEcgMortara
from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler
from anonimizacion.parseo.laboratorio_general import ParseadorLaboratorioGeneral
from anonimizacion.parseo.registro import obtener_parseador


def test_obtener_parseador_devuelve_instancia_correcta_por_tipo() -> None:
    casos = (
        (TipoDocumento.LABORATORIO, ParseadorLaboratorioGeneral),
        (TipoDocumento.ECG, ParseadorEcgMortara),
        (TipoDocumento.ECOCARDIOGRAMA, ParseadorEcoDoppler),
    )
    for tipo, clase in casos:
        assert isinstance(obtener_parseador(tipo), clase)


def test_obtener_parseador_tipo_no_reconocido_lanza_error_parseo() -> None:
    with pytest.raises(ErrorParseo) as info:
        obtener_parseador(TipoDocumento.TIPO_NO_RECONOCIDO)
    assert info.value.codigo is CodigoErrorDocumento.TIPO_NO_RECONOCIDO
