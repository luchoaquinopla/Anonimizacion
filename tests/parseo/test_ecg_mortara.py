"""Tests del parser de ECG Mortara (spec: document-parsing).

Ver requirement "Parser de ECG tolerante a advertencias del equipo": el
texto "PID / NAME MISMATCH" no debe abortar el parsing.
"""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ParseadorEcgMortara

_HEADER = (
    "Nombre: Lopez Ana\n"
    "ID Estudio: ECG-0042\n"
    "Fecha: 15/02/2024 09:10\n"
    "Institución: Clinica Central\n"
    "Edad: 55\n"
    "Sexo: F\n"
    "Técnico: Juan Tecnico\n"
    "Medico derivante: Dr. Diaz\n"
)
_MEDIDAS = (
    "Vent Rate: 72 bpm\n"
    "PR: 160 ms\n"
    "QRS: 90 ms\n"
    "QT/QTc: 400/420 ms\n"
    "Ejes P-R-T: 60/70/80\n"
)


def test_parsea_ecg_sin_advertencias() -> None:
    texto = TextoExtraido(paginas=(_HEADER + _MEDIDAS,))
    resultado = ParseadorEcgMortara().parsear(texto)

    assert resultado.tipo_documento is TipoDocumento.ECG
    assert resultado.identidad.nombre.get_secret_value() == "Lopez Ana"
    assert resultado.identidad.dni is None
    assert resultado.contenido.vent_rate == "72 bpm"
    assert "advertencia_equipo" not in resultado.adicionales


def test_tolera_advertencia_pid_name_mismatch_sin_abortar() -> None:
    texto = TextoExtraido(
        paginas=(_HEADER + _MEDIDAS + "\n*** PID / NAME MISMATCH ***\n",)
    )

    resultado = ParseadorEcgMortara().parsear(texto)

    assert resultado.tipo_documento is TipoDocumento.ECG
    assert resultado.adicionales["advertencia_equipo"] == "PID_NAME_MISMATCH"


def test_header_ausente_lanza_error_parseo() -> None:
    texto = TextoExtraido(paginas=("solo texto sin campos reconocibles",))
    with pytest.raises(ErrorParseo) as info:
        ParseadorEcgMortara().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO
