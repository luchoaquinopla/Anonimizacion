"""Tests de `observabilidad/bitacora_segura.py` (tasks.md 10.1).

Dos capas de defensa a probar por separado, y luego juntas en el property
test (design.md, decisión "Sin PII en cola, logs ni DLQ"):
1. Whitelist de campos: un campo no declarado se descarta, no se loguea.
2. Filtro de redacción: cualquier string que llegue al logger -incluso un
   campo whitelisteado que por error termine con texto libre con PII
   incrustada- se redacta (regex DNI + spans del motor Presidio+spaCy).

`motor` es fixture de módulo (carga spaCy una sola vez) -- mismo patrón que
`tests/pii/test_motor.py`.
"""

from __future__ import annotations

import logging
import random

import pytest

from anonimizacion.observabilidad.bitacora_segura import (
    CAMPOS_PERMITIDOS,
    MARCADOR_REDACTADO,
    BitacoraSegura,
    filtrar_y_redactar,
)
from anonimizacion.pii.motor import MotorPii

_NOMBRES = ["Juan", "María", "Carlos", "Ana", "Roberto", "Lucía", "Martín", "Sofía"]
_APELLIDOS = ["Pérez", "Gómez", "Rodríguez", "Fernández", "López", "García", "Díaz", "Torres"]


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


def _generar_dni_sintetico(rng: random.Random) -> str:
    numero = rng.randint(1_000_000, 99_999_999)
    if rng.random() < 0.5:
        return f"{numero:,}".replace(",", ".")
    return str(numero)


def _generar_nombre_sintetico(rng: random.Random) -> str:
    return f"{rng.choice(_NOMBRES)} {rng.choice(_APELLIDOS)}"


# --- Capa 1: whitelist de campos ---------------------------------------


def test_campo_no_declarado_se_descarta_sin_redactar() -> None:
    evento = {"id_documento": "doc-1", "nombre_paciente": "Juan Pérez"}
    resultado = filtrar_y_redactar(evento)
    assert "nombre_paciente" not in resultado
    assert resultado == {"id_documento": "doc-1"}


def test_solo_los_campos_de_la_whitelist_pueden_aparecer() -> None:
    evento = {campo: "x" for campo in CAMPOS_PERMITIDOS} | {"otro": "y", "mas_otro": "z"}
    resultado = filtrar_y_redactar(evento)
    assert set(resultado.keys()) <= CAMPOS_PERMITIDOS
    assert "otro" not in resultado
    assert "mas_otro" not in resultado


def test_whitelist_tiene_los_campos_declarados_en_design_md() -> None:
    assert CAMPOS_PERMITIDOS == frozenset(
        {"id_documento", "tipo_documento", "etapa", "codigo", "duracion_ms"}
    )


# --- Capa 2: filtro de redacción ----------------------------------------


def test_dni_con_puntos_en_campo_whitelisteado_se_redacta_por_regex() -> None:
    evento = {"codigo": "fallo con dni 12.345.678"}
    resultado = filtrar_y_redactar(evento)
    assert "12.345.678" not in resultado["codigo"]
    assert MARCADOR_REDACTADO in resultado["codigo"]


def test_dni_sin_puntos_en_campo_whitelisteado_se_redacta_por_regex() -> None:
    evento = {"codigo": "fallo con dni 12345678"}
    resultado = filtrar_y_redactar(evento)
    assert "12345678" not in resultado["codigo"]
    assert MARCADOR_REDACTADO in resultado["codigo"]


def test_nombre_en_campo_whitelisteado_se_redacta_via_motor_pii(motor: MotorPii) -> None:
    evento = {"codigo": "fallo procesando a Juan Pérez"}
    resultado = filtrar_y_redactar(evento, motor_pii=motor)
    assert "Juan Pérez" not in resultado["codigo"]


def test_sin_motor_pii_el_filtro_regex_igual_redacta_dni() -> None:
    evento = {"etapa": "parseo, dni 12345678"}
    resultado = filtrar_y_redactar(evento, motor_pii=None)
    assert "12345678" not in resultado["etapa"]


def test_valores_no_string_no_se_tocan() -> None:
    evento = {"duracion_ms": 42.5}
    resultado = filtrar_y_redactar(evento)
    assert resultado["duracion_ms"] == 42.5


# --- Property test: PII inyectada nunca aparece en la salida ------------


@pytest.mark.parametrize("semilla", range(30))
def test_property_pii_inyectada_nunca_aparece_en_la_salida(semilla: int, motor: MotorPii) -> None:
    rng = random.Random(semilla)
    dni = _generar_dni_sintetico(rng)
    nombre = _generar_nombre_sintetico(rng)

    # PII colada de dos formas distintas: (a) en un campo NO declarado
    # (debe descartarse por whitelist), (b) incrustada en texto libre
    # dentro de un campo SÍ declarado (debe redactarse por el filtro).
    evento = {
        "id_documento": "doc-1",
        "tipo_documento": "laboratorio",
        "codigo": f"fallo con paciente {nombre}, dni {dni}",
        "etapa": f"parseo -- ver {nombre}",
        "nombre_paciente": nombre,
        "dni_paciente": dni,
    }

    resultado = filtrar_y_redactar(evento, motor_pii=motor)

    assert "nombre_paciente" not in resultado
    assert "dni_paciente" not in resultado

    salida = " ".join(str(valor) for valor in resultado.values())
    assert dni not in salida
    assert nombre not in salida


# --- BitacoraSegura: envoltorio con logging real -------------------------


def test_bitacora_segura_registrar_loguea_y_devuelve_dict_seguro(
    caplog: pytest.LogCaptureFixture, motor: MotorPii
) -> None:
    logger = logging.getLogger("test.bitacora")
    bitacora = BitacoraSegura(logger=logger, motor_pii=motor)
    with caplog.at_level(logging.INFO, logger="test.bitacora"):
        resultado = bitacora.registrar(
            {"id_documento": "doc-9", "codigo": "ok con Juan Pérez", "nombre_paciente": "Juan Pérez"}
        )
    assert "nombre_paciente" not in resultado
    assert "Juan Pérez" not in resultado["codigo"]
    registros_bitacora = [r for r in caplog.records if r.name == "test.bitacora"]
    assert len(registros_bitacora) == 1
    assert all("Juan Pérez" not in registro.message for registro in registros_bitacora)
