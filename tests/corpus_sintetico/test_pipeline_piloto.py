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
    assert resultado.pdfs_entrada == 154
    assert resultado.documentos_inventariados == 149
    assert resultado.episodios_aprobados == 40
    assert resultado.documentos_publicados == 120
    assert resultado.documentos_en_cuarentena == 29
    assert resultado.registros_inspeccionados == 120
    # 520, no 572: tarea "invertir la dirección del corpus sintético"
    # (`tests/fixtures/plantilla_documento.py`) -- el generador ahora
    # registra 10 valores de identidad por episodio (4 laboratorio + 3 eco +
    # 3 ecg) en vez de los 11 fijos de antes (¡"Profesional Sintetico",
    # matrícula, técnico, etc. eran los MISMOS literales en los 52 episodios,
    # nunca variaban!). 572 - 520 = 52, exactamente 1 valor menos por cada
    # una de las 52 llamadas a `generar_corpus_clinico` del corpus
    # adversarial (50 casos + 2 alternos del caso "ambiguo"). El resto del
    # oráculo (episodios aprobados, cuarentena, códigos) no cambió: la
    # plantilla real conserva todo lo que el pipeline necesita para los
    # mismos 40 episodios "completos".
    assert resultado.valores_pii_verificados == 520
    # Los 2 casos "corrupto" del corpus adversarial (`fixtures/corpus_piloto.py`)
    # ahora caen en `pdf_ilegible`, no en el `parseo_incompleto` indistinguible
    # de antes (Tarea "que la cuarentena diga qué se rompió",
    # `extraccion/texto_pymupdf.py`).
    assert resultado.cuarentena_por_codigo == {
        "episodio_ambiguo": 8,
        "episodio_incompleto": 19,
        "pdf_ilegible": 2,
    }
    assert resultado.pii_en_salida == 0


def test_control_pii_detecta_cada_categoria_sintetica() -> None:
    valores = ["Nombre Prueba", "30999888", "02/02/1980", "PET-TEST-1", "EST-TEST-1"]
    registros_con_fuga = [f"registro con {valor}" for valor in valores]

    assert contar_coincidencias_pii(registros_con_fuga, valores) == len(valores)


_CAMPOS_DE_TIEMPO = (
    "tiempo_preparacion_segundos",
    "tiempo_procesamiento_segundos",
    "tiempo_verificacion_segundos",
)


def _sin_tiempos(resumen: dict[str, object]) -> dict[str, object]:
    return {clave: valor for clave, valor in resumen.items() if clave not in _CAMPOS_DE_TIEMPO}


def test_piloto_es_repetible_y_su_oraculo_no_contiene_pii_ni_red(corridas_piloto) -> None:
    primero, segundo = (resultado.como_dict() for resultado in corridas_piloto)

    # El oraculo (conteos, estados) debe ser identico entre corridas; los
    # tiempos de reloj, por naturaleza, no lo son.
    assert _sin_tiempos(primero) == _sin_tiempos(segundo)
    serializado = repr(primero).casefold()
    assert "dni" not in serializado
    assert "nombre" not in serializado
    assert "fecha_nacimiento" not in serializado
    assert "patient_id" not in serializado
