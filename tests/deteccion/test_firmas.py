"""Tests de las firmas (marcadores textuales) por tipo de documento."""

from __future__ import annotations

from anonimizacion.deteccion.firmas import FIRMAS
from anonimizacion.dominio.tipos_documento import TipoDocumento


def test_firmas_cubre_los_tres_tipos_conocidos() -> None:
    tipos_con_firma = {firma.tipo for firma in FIRMAS}
    assert tipos_con_firma == {
        TipoDocumento.ECG,
        TipoDocumento.LABORATORIO,
        TipoDocumento.ECOCARDIOGRAMA,
    }


def test_firmas_no_incluye_tipo_no_reconocido() -> None:
    # TIPO_NO_RECONOCIDO es el centinela de "ninguna firma coincidió", no una firma en sí
    assert all(firma.tipo != TipoDocumento.TIPO_NO_RECONOCIDO for firma in FIRMAS)


def test_firma_coincide_es_insensible_a_mayusculas() -> None:
    (firma_ecg,) = [f for f in FIRMAS if f.tipo == TipoDocumento.ECG]
    assert firma_ecg.coincide("cabecera\nMORTARA\nvent rate 72".upper())
