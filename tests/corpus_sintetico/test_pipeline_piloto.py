from unittest.mock import patch

import pytest

from tests.fixtures.corpus_piloto import (
    contar_coincidencias_pii,
    ejecutar_corpus_piloto,
)


@pytest.fixture(scope="module")
def corridas_piloto(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("corpus-piloto")
    with patch("socket.create_connection", side_effect=AssertionError("el corpus piloto no debe usar red")):
        primero = ejecutar_corpus_piloto(raiz / "primero", semilla=20260823)
        segundo = ejecutar_corpus_piloto(raiz / "segundo", semilla=20260823)
    return primero, segundo


def test_piloto_adversarial_ejecuta_cincuenta_casos_punta_a_punta(corridas_piloto) -> None:
    resultado, _segundo = corridas_piloto

    assert resultado.casos == 50
    assert resultado.archivos_en_disco == 154
    assert resultado.documentos_inventariados == 149
    assert resultado.episodios_aprobados == 40
    assert resultado.documentos_publicados == 120
    assert resultado.documentos_en_cuarentena == 29
    assert resultado.registros_inspeccionados == 120
    assert resultado.valores_pii_verificados == 572
    assert resultado.cuarentena_por_codigo == {
        "cobertura_ambigua": 8,
        "cobertura_incompleta": 19,
        "parseo_incompleto": 2,
    }
    assert resultado.pii_en_salida == 0


def test_control_pii_detecta_cada_categoria_sintetica() -> None:
    valores = ["Nombre Prueba", "30999888", "02/02/1980", "PET-TEST-1", "EST-TEST-1"]
    registros_con_fuga = [f"registro con {valor}" for valor in valores]

    assert contar_coincidencias_pii(registros_con_fuga, valores) == len(valores)


def test_piloto_es_repetible_y_su_oraculo_no_contiene_pii_ni_red(corridas_piloto) -> None:
    primero, segundo = (resultado.como_dict() for resultado in corridas_piloto)

    assert primero == segundo
    serializado = repr(primero).casefold()
    assert "dni" not in serializado
    assert "nombre" not in serializado
    assert "fecha_nacimiento" not in serializado
    assert "patient_id" not in serializado
