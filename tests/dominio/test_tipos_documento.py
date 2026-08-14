"""Tests de `TipoDocumento` — spec document-type-detection."""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento


def test_tiene_los_tres_layouts_conocidos() -> None:
    valores = {miembro.value for miembro in TipoDocumento}
    assert {"ecg", "laboratorio", "ecocardiograma"} <= valores


def test_tiene_centinela_de_no_reconocido() -> None:
    assert TipoDocumento.TIPO_NO_RECONOCIDO.value == "tipo_no_reconocido"


def test_es_subclase_de_str_para_serializar_sin_friccion() -> None:
    assert TipoDocumento.ECG == "ecg"
    assert isinstance(TipoDocumento.ECG, str)
