import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.reconciliacion.ecg_mortara import ReconciliadorEcgMortara
from anonimizacion.reconciliacion.registro import obtener_reconciliador


def test_registro_devuelve_strategy_por_tipo_documental() -> None:
    assert isinstance(obtener_reconciliador(TipoDocumento.ECG), ReconciliadorEcgMortara)


def test_registro_rechaza_tipo_sin_strategy() -> None:
    with pytest.raises(ErrorParseo) as error:
        obtener_reconciliador(TipoDocumento.TIPO_NO_RECONOCIDO)
    assert error.value.codigo is CodigoErrorDocumento.TIPO_NO_RECONOCIDO
