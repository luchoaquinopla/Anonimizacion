"""Tests de `salida/destinos/postgres.py` (tasks.md 7.3, spec `anonymized-output`).

Corren contra SQLite en memoria -- ver `tests/salida/test_migraciones.py`
para la nota completa de por qué (no hay Postgres en esta máquina de
desarrollo). `EscritorPostgres` recibe el `Engine` de afuera (inyección de
dependencia): en producción ese engine se arma con una URL
`postgresql+psycopg2://...` (Fase 8/9, pipeline/config -- todavía no
implementada), acá con `sqlite:///:memory:`. El código de este módulo no
importa `psycopg2` en ningún lado ni depende de sintaxis específica de
Postgres (nada de `INSERT ... ON CONFLICT`), así que es honestamente
portable, no un mock de la lógica real.

El bloque más importante de estos tests es la semántica de ambigüedad de
homónimos en `registrar_vinculo`: tiene que reproducir EXACTAMENTE el
comportamiento de `ResolutorClaves` (Fase 6, `pseudonimizacion/
resolutor_claves.py`) contra la tabla real `vinculo_paciente`, sin usar un
`UPSERT ... ON CONFLICT DO UPDATE` ingenuo (ver el docstring de
`ResolutorClaves` para el porqué -- ese patrón reintroduciría el bug
corregido post-PR5, commit 07da933).
"""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from pydantic import SecretStr

from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, IdentidadCruda, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.parseo.eco_doppler import ContenidoEco, FirmaMedico, MedidaEco, SeccionTextoEco
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio, ResultadoLaboratorio
from anonimizacion.salida.constructor_registro import construir_registro
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base, Episodio, MedicionEco, MedicionEcg, ResultadoLaboratorio as FilaOrmResultadoLaboratorio, TextoSeccionEco, VinculoPaciente

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"


@pytest.fixture()
def motor():
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


@pytest.fixture()
def escritor(motor) -> EscritorPostgres:
    return EscritorPostgres(motor)


def _leer_todas(motor, modelo):
    with sa.orm.Session(motor) as sesion:
        return sesion.scalars(sa.select(modelo)).all()


# --- registrar_vinculo: semántica de ambigüedad -----------------------------


def test_registrar_vinculo_nuevo_lo_inserta(escritor: EscritorPostgres, motor) -> None:
    escritor.registrar_vinculo("alt-1", "pid-1")

    filas = _leer_todas(motor, VinculoPaciente)
    assert len(filas) == 1
    assert filas[0].id_alt_paciente == "alt-1"
    assert filas[0].id_paciente == "pid-1"
    assert filas[0].ambiguo is False


def test_registrar_vinculo_mismo_par_es_idempotente(escritor: EscritorPostgres, motor) -> None:
    escritor.registrar_vinculo("alt-1", "pid-1")
    escritor.registrar_vinculo("alt-1", "pid-1")

    filas = _leer_todas(motor, VinculoPaciente)
    assert len(filas) == 1
    assert filas[0].ambiguo is False


def test_registrar_vinculo_con_id_paciente_distinto_marca_ambiguo_y_borra_candidato(
    escritor: EscritorPostgres, motor
) -> None:
    escritor.registrar_vinculo("alt-1", "pid-A")
    escritor.registrar_vinculo("alt-1", "pid-B")  # homónimo: DNI distinto, mismo alt

    filas = _leer_todas(motor, VinculoPaciente)
    assert len(filas) == 1
    assert filas[0].id_paciente is None
    assert filas[0].ambiguo is True


def test_registrar_vinculo_ambiguo_no_vuelve_a_resolver_ni_con_tercer_registro(
    escritor: EscritorPostgres, motor
) -> None:
    escritor.registrar_vinculo("alt-1", "pid-A")
    escritor.registrar_vinculo("alt-1", "pid-B")
    escritor.registrar_vinculo("alt-1", "pid-A")  # "desempate" -- no debe destrabar

    filas = _leer_todas(motor, VinculoPaciente)
    assert filas[0].id_paciente is None
    assert filas[0].ambiguo is True


def test_resolver_vinculo_devuelve_id_paciente_cuando_no_es_ambiguo(escritor: EscritorPostgres) -> None:
    escritor.registrar_vinculo("alt-1", "pid-1")

    assert escritor.resolver_vinculo("alt-1") == "pid-1"


def test_resolver_vinculo_devuelve_none_si_no_existe(escritor: EscritorPostgres) -> None:
    assert escritor.resolver_vinculo("no-existe") is None


def test_resolver_vinculo_devuelve_none_si_es_ambiguo(escritor: EscritorPostgres) -> None:
    escritor.registrar_vinculo("alt-1", "pid-A")
    escritor.registrar_vinculo("alt-1", "pid-B")

    assert escritor.resolver_vinculo("alt-1") is None
    assert escritor.es_ambiguo("alt-1") is True


# --- escribir_episodio: idempotente, sin riesgo de ambigüedad --------------


def test_escribir_episodio_es_idempotente(escritor: EscritorPostgres, motor) -> None:
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))

    filas = _leer_todas(motor, Episodio)
    assert len(filas) == 1


# --- escribir_registro: dispatch por tipo_documento -------------------------


def _registro_laboratorio() -> RegistroAnonimizado:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoLaboratorio(
            numero_peticion="P-1",
            resultados=(
                ResultadoLaboratorio(
                    seccion="HEMATOLOGIA",
                    prueba="Hemoglobina",
                    resultado="14.5",
                    unidades="g/dL",
                    valores_referencia="12-16",
                ),
            ),
        ),
        adicionales={"medico_derivante": "Dr. Roberto Diaz"},
    )
    claves = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)
    return construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST)


def test_escribir_registro_laboratorio_crea_filas_eav(escritor: EscritorPostgres, motor) -> None:
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    escritor.escribir_registro(_registro_laboratorio())

    filas = _leer_todas(motor, FilaOrmResultadoLaboratorio)
    assert len(filas) == 1
    assert filas[0].analito == "Hemoglobina"
    assert filas[0].id_episodio == "ep-1"
    assert filas[0].valor_num == 14.5


def test_escribir_registro_ecg_crea_fila_ancha(escritor: EscritorPostgres, motor) -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEcg(vent_rate="72", pr_interval="160", qrs_duration="90", qt_qtc="400/420", ejes="P60 R30 T40"),
        adicionales={},
    )
    claves = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)
    registro = construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST)

    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    escritor.escribir_registro(registro)

    filas = _leer_todas(motor, MedicionEcg)
    assert len(filas) == 1
    assert filas[0].vent_rate == "72"
    assert filas[0].id_episodio == "ep-1"


def test_escribir_registro_eco_pivota_medidas_conocidas_y_guarda_extras_en_adicionales(
    escritor: EscritorPostgres, motor
) -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEco(
            medidas=(
                MedidaEco(nombre="AO", valor="28", unidad="mm"),
                MedidaEco(nombre="P. Posterior", valor="9", unidad="mm"),
                MedidaEco(nombre="Medida rara no tabulada", valor="1", unidad=None),
            ),
            secciones_texto=(SeccionTextoEco(nombre="CONCLUSIONES", texto="Funcion sistolica conservada"),),
            firma=FirmaMedico(nombre="Dr. Carlos Gomez", matricula="MP12345"),
        ),
        adicionales={"medico_solicitante": "Dr. Ana Lopez"},
    )
    claves = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)
    registro = construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST)

    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    escritor.escribir_registro(registro)

    filas = _leer_todas(motor, MedicionEco)
    assert len(filas) == 1
    fila = filas[0]
    assert fila.ao == "28"
    assert fila.p_posterior == "9"
    assert fila.unidades == {"ao": "mm", "p_posterior": "mm"}
    assert fila.adicionales == {"Medida rara no tabulada": "1"}

    filas_texto = _leer_todas(motor, TextoSeccionEco)
    assert len(filas_texto) == 1
    assert filas_texto[0].texto == "Funcion sistolica conservada"


def test_escribir_registro_tipo_no_reconocido_lanza_value_error(escritor: EscritorPostgres) -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.TIPO_NO_RECONOCIDO,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=None,
    )
    claves = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)
    with pytest.raises(ValueError):
        construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST)
