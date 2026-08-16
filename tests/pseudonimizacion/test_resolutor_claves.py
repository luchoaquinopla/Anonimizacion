"""Tests de `resolutor_claves.py` (spec `patient-pseudonymization`): el laboratorio como puente.

Escenario real que estos tests cubren:

- El laboratorio trae nombre + DNI + fecha de nacimiento -> puede emitir
  AMBAS claves (`id_paciente` real vía DNI, `id_alt_paciente` vía
  nombre+fecha_nac) y registra el puente en `ResolutorClaves`.
- El ECG solo trae nombre + fecha de nacimiento (no DNI real) -> emite
  únicamente `id_alt_paciente`; `resolver_claves` busca el puente para
  encontrar el `id_paciente` real.
- Si el ECG llega ANTES que el lab de ese paciente (el puente todavía no
  existe) -> no hay ninguna clave resoluble -> `CLAVE_PII_NO_RESUELTA`.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import IdentidadCruda
from anonimizacion.pseudonimizacion.claves import generar_id_alt_paciente, generar_id_paciente
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves, resolver_claves

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"


@pytest.fixture()
def resolutor() -> ResolutorClaves:
    return ResolutorClaves()


def test_laboratorio_con_dni_y_fecha_nac_emite_ambas_claves_y_registra_puente(
    resolutor: ResolutorClaves,
) -> None:
    identidad_lab = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        dni=SecretStr("12.345.678"),
        fecha_nac=SecretStr("1980-01-01"),
    )

    claves = resolver_claves(
        identidad_lab, PEPPER_TEST, resolutor, id_documento="lab-1", etapa="pseudonimizacion"
    )

    assert claves.id_paciente == generar_id_paciente(PEPPER_TEST, "12.345.678")
    assert claves.id_alt_paciente == generar_id_alt_paciente(
        PEPPER_TEST, "Juan Perez", "1980-01-01"
    )
    assert claves.version_clave == 1


def test_ecg_sin_dni_se_resuelve_via_puente_si_el_lab_ya_se_proceso(
    resolutor: ResolutorClaves,
) -> None:
    identidad_lab = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        dni=SecretStr("12345678"),
        fecha_nac=SecretStr("1980-01-01"),
    )
    resolver_claves(identidad_lab, PEPPER_TEST, resolutor, id_documento="lab-1", etapa="pseudonimizacion")

    identidad_ecg = IdentidadCruda(nombre=SecretStr("Juan Perez"), fecha_nac=SecretStr("1980-01-01"))
    claves_ecg = resolver_claves(
        identidad_ecg, PEPPER_TEST, resolutor, id_documento="ecg-1", etapa="pseudonimizacion"
    )

    assert claves_ecg.id_paciente == generar_id_paciente(PEPPER_TEST, "12345678")
    assert claves_ecg.id_alt_paciente == generar_id_alt_paciente(
        PEPPER_TEST, "Juan Perez", "1980-01-01"
    )


def test_ecg_sin_dni_y_sin_puente_previo_lanza_clave_pii_no_resuelta(
    resolutor: ResolutorClaves,
) -> None:
    identidad_ecg = IdentidadCruda(nombre=SecretStr("Juan Perez"), fecha_nac=SecretStr("1980-01-01"))

    with pytest.raises(ErrorParseo) as excinfo:
        resolver_claves(
            identidad_ecg, PEPPER_TEST, resolutor, id_documento="ecg-1", etapa="pseudonimizacion"
        )

    assert excinfo.value.codigo == CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA
    assert excinfo.value.etapa == "pseudonimizacion"


def test_sin_dni_ni_fecha_nac_lanza_clave_pii_no_resuelta(resolutor: ResolutorClaves) -> None:
    identidad_sin_datos = IdentidadCruda(nombre=SecretStr("Juan Perez"))

    with pytest.raises(ErrorParseo) as excinfo:
        resolver_claves(
            identidad_sin_datos,
            PEPPER_TEST,
            resolutor,
            id_documento="doc-1",
            etapa="pseudonimizacion",
        )

    assert excinfo.value.codigo == CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA


def test_puente_se_puede_recomputar_reprocesando_el_ecg_despues_del_lab(
    resolutor: ResolutorClaves,
) -> None:
    # el ECG llega primero: falla y va a cuarentena
    identidad_ecg = IdentidadCruda(nombre=SecretStr("Ana Gomez"), fecha_nac=SecretStr("1990-05-05"))
    with pytest.raises(ErrorParseo):
        resolver_claves(
            identidad_ecg, PEPPER_TEST, resolutor, id_documento="ecg-2", etapa="pseudonimizacion"
        )

    # llega el lab del mismo paciente: registra el puente
    identidad_lab = IdentidadCruda(
        nombre=SecretStr("Ana Gomez"),
        dni=SecretStr("87654321"),
        fecha_nac=SecretStr("1990-05-05"),
    )
    resolver_claves(identidad_lab, PEPPER_TEST, resolutor, id_documento="lab-2", etapa="pseudonimizacion")

    # reprocesar el mismo ECG ahora sí resuelve (idempotente, batch recompute)
    claves_ecg = resolver_claves(
        identidad_ecg, PEPPER_TEST, resolutor, id_documento="ecg-2", etapa="pseudonimizacion"
    )
    assert claves_ecg.id_paciente == generar_id_paciente(PEPPER_TEST, "87654321")


def test_lab_con_dni_pero_sin_fecha_nac_no_registra_puente_pero_resuelve_id_paciente(
    resolutor: ResolutorClaves,
) -> None:
    identidad_lab = IdentidadCruda(nombre=SecretStr("Juan Perez"), dni=SecretStr("12345678"))

    claves = resolver_claves(
        identidad_lab, PEPPER_TEST, resolutor, id_documento="lab-3", etapa="pseudonimizacion"
    )

    assert claves.id_paciente == generar_id_paciente(PEPPER_TEST, "12345678")
    assert claves.id_alt_paciente is None
