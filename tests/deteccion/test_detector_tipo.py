"""Tests de `detectar_tipo` (spec: document-type-detection).

Clasifica por marcadores de texto; ante un documento sin marcadores conocidos
devuelve `TIPO_NO_RECONOCIDO` en lugar de lanzar — el pipeline no debe
abortar el lote por un layout desconocido, va a cuarentena más adelante.
"""

from __future__ import annotations

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido


def test_detectar_tipo_reconoce_ecg_mortara() -> None:
    texto = TextoExtraido(paginas=("MORTARA\nVent rate 72 bpm\nPR 160 ms",))
    assert detectar_tipo(texto) is TipoDocumento.ECG


def test_detectar_tipo_reconoce_laboratorio() -> None:
    texto = TextoExtraido(
        paginas=("Apellido y Nombre: prueba\nHEMATOLOGIA\nHemoglobina 14 g/dL",)
    )
    assert detectar_tipo(texto) is TipoDocumento.LABORATORIO


def test_detectar_tipo_reconoce_ecocardiograma() -> None:
    # "SERVICIO DE ECOCARDIOGRAFIA" es un marcador verificado contra el
    # documento real (ver `firmas/eco_doppler.py`); "ECOCARDIOGRAMA DOPPLER"
    # se retiró por no aparecer en el layout real.
    texto = TextoExtraido(paginas=("SERVICIO DE ECOCARDIOGRAFIA\nAO 28mm\nFA 35%",))
    assert detectar_tipo(texto) is TipoDocumento.ECOCARDIOGRAMA


def test_detectar_tipo_sin_marcadores_conocidos_devuelve_no_reconocido() -> None:
    texto = TextoExtraido(paginas=("un documento cualquiera sin ningun marcador clinico",))
    assert detectar_tipo(texto) is TipoDocumento.TIPO_NO_RECONOCIDO


def test_detectar_tipo_no_reconocido_no_lanza_excepcion() -> None:
    texto = TextoExtraido(paginas=("",))
    resultado = detectar_tipo(texto)  # no debe lanzar, ni siquiera con texto vacio
    assert resultado is TipoDocumento.TIPO_NO_RECONOCIDO
