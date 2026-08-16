"""Test de seguridad (tasks.md 11.5, spec `pii-detection`/`pdf-text-extraction`, "100% offline").

El bloqueo de red real está instalado como fixture `autouse` de sesión en
`tests/conftest.py::_bloquear_llamadas_de_red_reales` -- aplica a TODA la
suite, no solo a este módulo (así es como se confirma "ninguna llamada de
red" en el resto de los ~215 tests, no solo acá). Este test verifica
positivamente que el bloqueo efectivamente funciona (si algo intentara abrir
un socket real, lanzaría) y que operaciones 100% locales -- SQLite en
memoria, el motor de PII (Presidio+spaCy, ya cargado desde disco) -- siguen
funcionando con el bloqueo activo, confirmando que no es un falso positivo
que rompería el resto de la suite.
"""

from __future__ import annotations

import socket

import pytest
import sqlalchemy as sa

from anonimizacion.pii.motor import MotorPii
from tests.conftest import LlamadaDeRedBloqueada


def test_intentar_abrir_un_socket_real_lanza_llamada_de_red_bloqueada() -> None:
    with pytest.raises(LlamadaDeRedBloqueada):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("example.com", 80))


def test_sqlite_en_memoria_sigue_funcionando_con_el_bloqueo_de_red_activo() -> None:
    # SQLAlchemy contra sqlite:///:memory: es I/O local, no red -- no debe
    # disparar el bloqueo (ver docstring de la fixture en tests/conftest.py).
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conexion:
        resultado = conexion.execute(sa.text("SELECT 1")).scalar_one()
    assert resultado == 1


def test_motor_pii_real_sigue_funcionando_con_el_bloqueo_de_red_activo(motor: MotorPii) -> None:
    # el modelo spaCy ya está cargado desde disco (fixture de módulo/sesión);
    # `detectar` no hace ninguna llamada de red -- ver `pii/motor.py`.
    detecciones = motor.detectar("El paciente Juan Sintetico Siete fue atendido ayer.")
    assert any(d.tipo_entidad == "PERSON" for d in detecciones)
