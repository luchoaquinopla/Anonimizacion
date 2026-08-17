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
import sqlalchemy as sa
from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import IdentidadCruda
from anonimizacion.pseudonimizacion.claves import generar_id_alt_paciente, generar_id_paciente
from anonimizacion.pseudonimizacion.resolutor_claves import (
    ResolutorClaves,
    ResolutorClavesPostgres,
    resolver_claves,
)
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base

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


# --- Colisión de homónimos (post-PR5 fix) ---------------------------------
#
# `id_alt_paciente` se calcula SOLO con nombre+fecha_nac (no es un
# identificador único de persona real). Dos pacientes reales distintos con
# el mismo nombre y la misma fecha de nacimiento producen el MISMO
# `id_alt_paciente` -- sin este fix, el segundo `registrar_puente` pisaba en
# silencio la entrada del primero, y un ECG del primer paciente terminaba
# resolviendo a la identidad del segundo.


def test_dos_pacientes_homonimos_con_dni_distinto_no_mezclan_identidades(
    resolutor: ResolutorClaves,
) -> None:
    # paciente A: DNI 11111111, "Juan Perez", 1980-01-01 -- llega primero
    identidad_lab_a = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        dni=SecretStr("11111111"),
        fecha_nac=SecretStr("1980-01-01"),
    )
    resolver_claves(
        identidad_lab_a, PEPPER_TEST, resolutor, id_documento="lab-a", etapa="pseudonimizacion"
    )

    # paciente B: DNI 22222222, TAMBIEN "Juan Perez", TAMBIEN 1980-01-01 -- homónimo
    identidad_lab_b = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        dni=SecretStr("22222222"),
        fecha_nac=SecretStr("1980-01-01"),
    )
    resolver_claves(
        identidad_lab_b, PEPPER_TEST, resolutor, id_documento="lab-b", etapa="pseudonimizacion"
    )

    # el ECG de A (sin DNI, solo nombre+fecha_nac) NO debe resolver a B ni a A:
    # el id_alt_paciente es ambiguo, no hay forma segura de saber a cuál corresponde.
    identidad_ecg_a = IdentidadCruda(nombre=SecretStr("Juan Perez"), fecha_nac=SecretStr("1980-01-01"))
    with pytest.raises(ErrorParseo) as excinfo:
        resolver_claves(
            identidad_ecg_a, PEPPER_TEST, resolutor, id_documento="ecg-a", etapa="pseudonimizacion"
        )

    assert excinfo.value.codigo == CodigoErrorDocumento.CLAVE_PII_AMBIGUA
    assert excinfo.value.etapa == "pseudonimizacion"


def test_registrar_mismo_puente_dos_veces_es_idempotente_no_marca_ambiguo(
    resolutor: ResolutorClaves,
) -> None:
    id_alt = generar_id_alt_paciente(PEPPER_TEST, "Juan Perez", "1980-01-01")
    id_paciente = generar_id_paciente(PEPPER_TEST, "11111111")

    # reprocesar el mismo laboratorio dos veces (mismo id_alt_paciente, mismo id_paciente)
    resolutor.registrar_puente(id_alt, id_paciente)
    resolutor.registrar_puente(id_alt, id_paciente)

    assert resolutor.resolver(id_alt) == id_paciente


def test_id_alt_paciente_ambiguo_nunca_vuelve_a_resolver_ni_con_tercer_registro(
    resolutor: ResolutorClaves,
) -> None:
    id_alt = generar_id_alt_paciente(PEPPER_TEST, "Juan Perez", "1980-01-01")
    id_paciente_a = generar_id_paciente(PEPPER_TEST, "11111111")
    id_paciente_b = generar_id_paciente(PEPPER_TEST, "22222222")
    id_paciente_c = generar_id_paciente(PEPPER_TEST, "33333333")

    resolutor.registrar_puente(id_alt, id_paciente_a)
    resolutor.registrar_puente(id_alt, id_paciente_b)  # conflicto -> ambiguo
    assert resolutor.resolver(id_alt) is None

    # un tercer registro (que "desempataría" 2 a 1 si se contara) tampoco lo destraba:
    # una vez ambiguo, queda ambiguo permanentemente.
    resolutor.registrar_puente(id_alt, id_paciente_a)
    resolutor.registrar_puente(id_alt, id_paciente_a)
    resolutor.registrar_puente(id_alt, id_paciente_c)
    assert resolutor.resolver(id_alt) is None


def test_resolver_claves_lanza_clave_pii_ambigua_no_no_resuelta(
    resolutor: ResolutorClaves,
) -> None:
    identidad_lab_a = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        dni=SecretStr("11111111"),
        fecha_nac=SecretStr("1980-01-01"),
    )
    identidad_lab_b = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        dni=SecretStr("22222222"),
        fecha_nac=SecretStr("1980-01-01"),
    )
    resolver_claves(
        identidad_lab_a, PEPPER_TEST, resolutor, id_documento="lab-a", etapa="pseudonimizacion"
    )
    resolver_claves(
        identidad_lab_b, PEPPER_TEST, resolutor, id_documento="lab-b", etapa="pseudonimizacion"
    )

    identidad_ecg = IdentidadCruda(nombre=SecretStr("Juan Perez"), fecha_nac=SecretStr("1980-01-01"))
    with pytest.raises(ErrorParseo) as excinfo:
        resolver_claves(
            identidad_ecg, PEPPER_TEST, resolutor, id_documento="ecg-a", etapa="pseudonimizacion"
        )

    assert excinfo.value.codigo == CodigoErrorDocumento.CLAVE_PII_AMBIGUA
    assert excinfo.value.codigo != CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA


# --- ResolutorClavesPostgres: mismo contrato, respaldado por Postgres ------
#
# Fix post-merge (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
# "Fix: persistencia del puente id_alt_paciente en Postgres entre
# corridas"): `ResolutorClaves` (arriba) es SOLO en memoria -- se pierde al
# terminar el proceso. `ResolutorClavesPostgres` implementa el MISMO
# contrato (`registrar_puente`/`resolver`/`es_ambiguo`) delegando cada
# llamada directo a `EscritorPostgres.registrar_vinculo`/`resolver_vinculo`/
# `es_ambiguo` -- sin caché propia, así que el estado sobrevive a la
# instancia (y por lo tanto a una corrida separada del programa que reabra
# el mismo engine/base).


@pytest.fixture()
def escritor_postgres() -> EscritorPostgres:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return EscritorPostgres(motor)


def test_resolutor_postgres_registra_y_resuelve_delegando_en_escritor(
    escritor_postgres: EscritorPostgres,
) -> None:
    resolutor_pg = ResolutorClavesPostgres(escritor_postgres)
    resolutor_pg.registrar_puente("alt-1", "pid-1")

    assert resolutor_pg.resolver("alt-1") == "pid-1"
    assert resolutor_pg.es_ambiguo("alt-1") is False


def test_resolutor_postgres_homonimos_marca_ambiguo_igual_que_el_de_memoria(
    escritor_postgres: EscritorPostgres,
) -> None:
    resolutor_pg = ResolutorClavesPostgres(escritor_postgres)
    resolutor_pg.registrar_puente("alt-1", "pid-A")
    resolutor_pg.registrar_puente("alt-1", "pid-B")  # homónimo: mismo alt, distinto paciente

    assert resolutor_pg.resolver("alt-1") is None
    assert resolutor_pg.es_ambiguo("alt-1") is True


def test_resolutor_postgres_usado_con_resolver_claves_end_to_end(
    escritor_postgres: EscritorPostgres,
) -> None:
    resolutor_pg = ResolutorClavesPostgres(escritor_postgres)

    identidad_lab = IdentidadCruda(
        nombre=SecretStr("Juan Perez"), dni=SecretStr("12345678"), fecha_nac=SecretStr("1980-01-01")
    )
    resolver_claves(identidad_lab, PEPPER_TEST, resolutor_pg, id_documento="lab-1", etapa="pseudonimizacion")

    identidad_ecg = IdentidadCruda(nombre=SecretStr("Juan Perez"), fecha_nac=SecretStr("1980-01-01"))
    claves_ecg = resolver_claves(
        identidad_ecg, PEPPER_TEST, resolutor_pg, id_documento="ecg-1", etapa="pseudonimizacion"
    )

    assert claves_ecg.id_paciente == generar_id_paciente(PEPPER_TEST, "12345678")


def test_resolutor_postgres_nueva_instancia_ve_el_puente_ya_persistido(
    escritor_postgres: EscritorPostgres,
) -> None:
    # simula una corrida SEPARADA del programa: instancia NUEVA de
    # ResolutorClavesPostgres sobre el MISMO engine/base -- a diferencia de
    # ResolutorClaves(), no arranca vacía.
    resolutor_corrida_1 = ResolutorClavesPostgres(escritor_postgres)
    resolutor_corrida_1.registrar_puente("alt-1", "pid-1")

    resolutor_corrida_2 = ResolutorClavesPostgres(escritor_postgres)
    assert resolutor_corrida_2.resolver("alt-1") == "pid-1"
