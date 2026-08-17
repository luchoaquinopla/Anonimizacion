"""Tests del parser de ECG Mortara (spec: document-parsing).

Ver requirement "Parser de ECG tolerante a advertencias del equipo": el
texto "PID / NAME MISMATCH" no debe abortar el parsing.

Recalibrado post-PR9 contra el layout REAL del equipo (posicional, sin
etiquetas "Campo: valor" salvo unos pocos campos de pie) — ver docstring de
`parseo/ecg_mortara.py`. Todo el texto usado acá (nombres, IDs, fechas) es
100% inventado para este test.
"""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ParseadorEcgMortara

# "MORTARA" es el marcador de equipo que usa `deteccion/firmas/ecg_mortara.py`
# para clasificar el tipo de documento -- no es PII, es el nombre del modelo
# de equipo, igual que en el fixture sintético original.
_HEADER_REAL = (
    "MORTARA ELI 380\n"
    "Prueba Sintetica~,                    ID:900321                  "
    "05-JUN-2025  10:22:31        HOSPITAL FICTICIO   ROUTINE RECORD\n"
    "12-DEC-1975 (49 yr)      Female      Unknown\n"
    "Room:\n"
    "Loc:3\n"
)
_MEDIDAS_REAL = (
    "                    Vent. rate            68    BPM\n"
    "                    PR interval          172    ms\n"
    "                    QRS duration           96    ms\n"
    "                    QT/QTc            390/410    ms\n"
    "                    P-R-T axes         55  40    30\n"
)
_PIE_REAL = (
    "\n"
    "           Technician:\n"
    "           Test ind:\n"
    "Med:\n"
    "\n"
    "Ordered by:  - Dr Ficticio Derivante                          Unconfirmed\n"
)


def test_parsea_ecg_layout_real_sin_advertencias() -> None:
    texto = TextoExtraido(paginas=(_HEADER_REAL + _MEDIDAS_REAL + _PIE_REAL,))
    resultado = ParseadorEcgMortara().parsear(texto)

    assert resultado.tipo_documento is TipoDocumento.ECG
    assert resultado.identidad.nombre.get_secret_value() == "Prueba Sintetica"
    assert resultado.identidad.dni is None
    assert resultado.fecha_estudio.isoformat() == "2025-06-05"
    assert resultado.contenido.vent_rate == "68 BPM"
    assert resultado.contenido.pr_interval == "172 ms"
    assert resultado.contenido.qrs_duration == "96 ms"
    assert resultado.contenido.qt_qtc == "390/410 ms"
    assert resultado.contenido.ejes == "55 40 30"
    assert "advertencia_equipo" not in resultado.adicionales
    assert resultado.adicionales["institucion"] == "HOSPITAL FICTICIO"
    assert resultado.adicionales["medico_derivante"] == "Dr Ficticio Derivante"


def test_extrae_fecha_nacimiento_normalizada_a_iso_para_el_puente_de_identidad() -> None:
    """La fecha de nacimiento del ECG habilita el puente `id_alt_paciente ->
    id_paciente` hacia el laboratorio (`pseudonimizacion/resolutor_claves.py`)
    -- antes de esta recalibración quedaba siempre en `None`.
    """
    texto = TextoExtraido(paginas=(_HEADER_REAL + _MEDIDAS_REAL + _PIE_REAL,))
    resultado = ParseadorEcgMortara().parsear(texto)

    assert resultado.identidad.fecha_nac is not None
    assert resultado.identidad.fecha_nac.get_secret_value() == "1975-12-12"


def test_tolera_advertencia_pid_name_mismatch_sin_abortar() -> None:
    texto_con_advertencia = (
        "MORTARA ELI 380\n"
        "Prueba Sintetica~,                    ID:900321                  "
        "05-JUN-2025  10:22:31        HOSPITAL FICTICIO   ROUTINE RECORD\n"
        "*** PID / NAME MISMATCH ***\n"
        "12-DEC-1975 (49 yr)      Female      Unknown\n"
    )
    texto = TextoExtraido(paginas=(texto_con_advertencia + _MEDIDAS_REAL + _PIE_REAL,))

    resultado = ParseadorEcgMortara().parsear(texto)

    assert resultado.tipo_documento is TipoDocumento.ECG
    assert resultado.adicionales["advertencia_equipo"] == "PID_NAME_MISMATCH"
    # la advertencia entre el header y la línea de fecha de nacimiento no
    # debe romper la extracción de ninguno de los dos.
    assert resultado.identidad.nombre.get_secret_value() == "Prueba Sintetica"
    assert resultado.identidad.fecha_nac.get_secret_value() == "1975-12-12"


def test_fecha_nacimiento_ausente_no_rompe_el_parseo() -> None:
    """Si la línea de fecha de nacimiento no matchea (equipo/reporte distinto),
    `fecha_nac` queda en `None` -- el ECG sigue parseando el resto igual,
    solo no puede resolver el puente por esta vía (ver `resolutor_claves.py`).
    """
    header_sin_fecha_nac = (
        "MORTARA ELI 380\n"
        "Prueba Sintetica~,                    ID:900321                  "
        "05-JUN-2025  10:22:31        HOSPITAL FICTICIO   ROUTINE RECORD\n"
    )
    texto = TextoExtraido(paginas=(header_sin_fecha_nac + _MEDIDAS_REAL + _PIE_REAL,))

    resultado = ParseadorEcgMortara().parsear(texto)

    assert resultado.identidad.fecha_nac is None


def test_header_ausente_lanza_error_parseo() -> None:
    texto = TextoExtraido(paginas=("solo texto sin campos reconocibles",))
    with pytest.raises(ErrorParseo) as info:
        ParseadorEcgMortara().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO
