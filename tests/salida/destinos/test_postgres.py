"""Tests de `salida/destinos/postgres.py` (tasks.md 7.3, spec `anonymized-output`).

Corren contra SQLite en memoria -- ver `tests/salida/test_migraciones.py`
para la nota completa de por qué (la suite bloquea toda conexión de red real,
`tests/conftest.py::_bloquear_llamadas_de_red_reales`; Postgres real sólo se
usa para verificación manual fuera de pytest, ver
`openspec/changes/paralelismo-de-procesamiento/proposal.md`). `EscritorPostgres`
recibe el `Engine` de afuera (inyección de dependencia): en producción ese
engine se arma con `construir_engine_postgres` (mismo módulo) contra una URL
`postgresql+psycopg://...`, acá con `sqlite:///:memory:`. El código de este
módulo no importa `psycopg` en ningún lado ni depende de sintaxis específica
de Postgres (nada de `INSERT ... ON CONFLICT`), así que es honestamente
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

from dataclasses import replace
from datetime import date, time

import pytest
import sqlalchemy as sa

from pydantic import SecretStr

from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, IdentidadCruda, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.parseo.eco_doppler import ContenidoEco, FirmaMedico, MedidaEco, SeccionTextoEco
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio, ResultadoLaboratorio
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.salida.constructor_registro import construir_registro
from anonimizacion.salida.destinos import postgres as destinos_postgres
from anonimizacion.salida.destinos.postgres import POOL_RECYCLE_SEGUNDOS, POOL_SIZE, EscritorPostgres, construir_engine_postgres
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.salida.modelos_orm import Base, Episodio, Estudio, MedicionEco, MedicionEcg, ResultadoLaboratorio as FilaOrmResultadoLaboratorio, TextoSeccionEco, VinculoPaciente

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"
SHA256_SINTETICO_TEST = "e" * 64  # huella inventada de 64 hex, ningún valor real
CLAVE_DOCUMENTO_TEST = generar_clave_documento(PEPPER_TEST, SHA256_SINTETICO_TEST)


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
    return construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST, clave_documento=CLAVE_DOCUMENTO_TEST)


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
    registro = construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST, clave_documento=CLAVE_DOCUMENTO_TEST)

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
    registro = construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST, clave_documento=CLAVE_DOCUMENTO_TEST)

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
        construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST, clave_documento=CLAVE_DOCUMENTO_TEST)


# --- estudio: fecha y hora por documento -----------------------------------
#
# `episodio.fecha_ancla` es la fecha del GRUPO. Sin la tabla `estudio` el delta
# entre dos estudios del mismo episodio no es computable en SQL.


def _registro_con_hora(hora: time | None, precision: PrecisionHora) -> RegistroAnonimizado:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        hora_estudio=hora,
        precision_hora=precision,
        contenido=ContenidoEcg(
            vent_rate="73", pr_interval="186", qrs_duration="100", qt_qtc="382/420", ejes="63 51 26"
        ),
    )
    claves = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)
    return construir_registro(documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST, clave_documento=CLAVE_DOCUMENTO_TEST)


def test_escribir_registro_crea_estudio_y_enlaza_la_medicion(escritor: EscritorPostgres, motor) -> None:
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))

    escritor.escribir_registro(_registro_con_hora(time(10, 32, 15), PrecisionHora.SEGUNDO))

    estudios = _leer_todas(motor, Estudio)
    assert len(estudios) == 1
    assert estudios[0].fecha_estudio == date(2024, 1, 10)
    assert estudios[0].hora_estudio == time(10, 32, 15)
    assert estudios[0].precision_hora == "segundo"
    assert estudios[0].tipo_documento == TipoDocumento.ECG.value

    mediciones = _leer_todas(motor, MedicionEcg)
    assert len(mediciones) == 1
    assert mediciones[0].id_estudio == estudios[0].id_estudio


def test_escribir_registro_sin_hora_nunca_persiste_medianoche(escritor: EscritorPostgres, motor) -> None:
    """`AUSENTE` debe llegar a SQL como NULL: medianoche seria una hora inventada."""
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))

    escritor.escribir_registro(_registro_con_hora(None, PrecisionHora.AUSENTE))

    estudios = _leer_todas(motor, Estudio)
    assert len(estudios) == 1
    assert estudios[0].hora_estudio is None
    assert estudios[0].precision_hora == "ausente"


def test_escribir_registro_de_laboratorio_enlaza_todas_sus_filas_al_mismo_estudio(
    escritor: EscritorPostgres, motor
) -> None:
    """El laboratorio es EAV: N filas de resultado cuelgan de UN solo estudio."""
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))

    escritor.escribir_registro(_registro_laboratorio())

    estudios = _leer_todas(motor, Estudio)
    assert len(estudios) == 1
    filas = _leer_todas(motor, FilaOrmResultadoLaboratorio)
    assert filas
    assert {fila.id_estudio for fila in filas} == {estudios[0].id_estudio}


# --- idempotencia: reprocesar no duplica ------------------------------------
#
# Reproduce el experimento de la exploracion, ahora como contrato: el mismo
# documento escrito tres veces dejaba 3 filas en `estudio` y 3 en `medicion_ecg`.


def _registro_con_clave(clave: str) -> RegistroAnonimizado:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEcg(
            vent_rate="73", pr_interval="186", qrs_duration="100", qt_qtc="382/420", ejes="63 51 26"
        ),
    )
    claves = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)
    return construir_registro(
        documento, claves, id_episodio="ep-1", pepper=PEPPER_TEST, clave_documento=clave
    )


# --- corrida_id / creado_en: bug cerrado en `panel-de-operacion` PR 2.5 ----
#
# `_insertar` construía `Estudio(...)` sin `corrida_id=registro.corrida_id`,
# y `Estudio.creado_en` no tenía el `default=_ahora_utc` que `design.md` ya
# pedía -- ambos quedaban en `None` en TODA fila real, sin importar qué tan
# bien el pipeline propagara el parámetro. Ningún test de Fase 3/5 lo detectó
# porque todos verificaban `RegistroAnonimizado.corrida_id` contra dobles; el
# primer test end-to-end real (`tests/scripts/test_procesar_carpeta.py`) lo
# hizo visible. Este test es la protección quirúrgica y aislada: apunta
# directo al método donde el defecto se escondió, sin bajar por
# `procesar_grupo` ni por el script si algún día vuelve a romperse.


def test_escribir_registro_persiste_corrida_id_y_creado_en(escritor: EscritorPostgres, motor) -> None:
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    registro = replace(_registro_con_clave(CLAVE_DOCUMENTO_TEST), corrida_id="corrida-test-1")

    escritor.escribir_registro(registro)

    (estudio,) = _leer_todas(motor, Estudio)
    assert estudio.corrida_id == "corrida-test-1"
    assert estudio.creado_en is not None


def test_escribir_registro_sin_corrida_id_deja_corrida_id_en_none(escritor: EscritorPostgres, motor) -> None:
    """Sin `corrida_id` explícito (default `None` de `RegistroAnonimizado`), la
    fila sigue sin corrida -- no inventar una identidad que nadie asignó."""
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))

    escritor.escribir_registro(_registro_con_clave(CLAVE_DOCUMENTO_TEST))

    (estudio,) = _leer_todas(motor, Estudio)
    assert estudio.corrida_id is None
    assert estudio.creado_en is not None  # el default de Python igual estampa el momento de escritura


def test_escribir_el_mismo_documento_tres_veces_deja_una_sola_fila(
    escritor: EscritorPostgres, motor
) -> None:
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    registro = _registro_con_clave(CLAVE_DOCUMENTO_TEST)

    for _ in range(3):
        escritor.escribir_registro(registro)

    assert len(_leer_todas(motor, Estudio)) == 1
    assert len(_leer_todas(motor, MedicionEcg)) == 1


def test_reprocesar_no_lanza_excepcion(escritor: EscritorPostgres, motor) -> None:
    """Un reprocesamiento es un caso normal de operacion, no una condicion excepcional."""
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    registro = _registro_con_clave(CLAVE_DOCUMENTO_TEST)

    escritor.escribir_registro(registro)
    escritor.escribir_registro(registro)  # no debe levantar nada


def test_dos_documentos_distintos_del_mismo_episodio_dejan_dos_estudios(
    escritor: EscritorPostgres, motor
) -> None:
    """Evita que la guarda quede por episodio en vez de por documento."""
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))

    escritor.escribir_registro(_registro_con_clave("clave-sintetica-a"))
    escritor.escribir_registro(_registro_con_clave("clave-sintetica-b"))

    assert len(_leer_todas(motor, Estudio)) == 2


def test_la_restriccion_unica_resiste_una_carrera(escritor: EscritorPostgres, motor) -> None:
    """El `SELECT` previo no cierra la carrera: la restriccion es la autoridad.

    Se simula insertando la fila por fuera del escritor DESPUES de que su
    `SELECT` no la encontro, que es lo que ocurre cuando dos trabajadores
    escriben el mismo documento a la vez.
    """
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    registro = _registro_con_clave(CLAVE_DOCUMENTO_TEST)

    original = escritor._existe_documento

    def _fingir_que_no_existe(*args, **kwargs):
        original(*args, **kwargs)
        return False

    escritor.escribir_registro(registro)
    escritor._existe_documento = _fingir_que_no_existe
    try:
        escritor.escribir_registro(registro)  # no debe propagar IntegrityError
    finally:
        escritor._existe_documento = original

    assert len(_leer_todas(motor, Estudio)) == 1


def test_un_registro_sin_clave_conserva_el_comportamiento_anterior(
    escritor: EscritorPostgres, motor
) -> None:
    """Sin clave no hay garantia posible, y se documenta como tal."""
    escritor.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    registro = _registro_con_clave(None)

    escritor.escribir_registro(registro)
    escritor.escribir_registro(registro)

    assert len(_leer_todas(motor, Estudio)) == 2


# --- registrar_vinculo / escribir_episodio: la misma tolerancia a carrera ---
# que ya tiene escribir_registro (openspec `paralelismo-de-procesamiento`
# PR 1). Sin esto, dos procesos que resuelven el mismo paciente o escriben el
# mismo episodio a la vez chocan -> `IntegrityError` sin capturar -> el
# documento se pierde en vez de tratarse como el caso normal que es.
#
# Método: igual que `test_la_restriccion_unica_resiste_una_carrera` de más
# arriba -- se hace mentir a la lectura optimista (`_buscar_vinculo`/
# `_buscar_episodio`) para que devuelva "no existe" aunque la fila YA fue
# insertada por fuera, forzando el `IntegrityError` REAL de la restricción de
# clave primaria en el punto exacto donde ocurriría con dos procesos
# concurrentes. No es una carrera simulada con dos llamadas en serie: el
# `INSERT` que dispara la excepción es genuino, sólo el timing de la lectura
# está controlado para que sea determinístico en vez de depender del
# scheduler.


def test_registrar_vinculo_resiste_una_carrera_del_mismo_par(escritor: EscritorPostgres, motor) -> None:
    """Dos procesos registran (alt, pid) idéntico a la vez: el perdedor de la
    carrera no debe fallar ni duplicar la fila."""
    original = escritor._buscar_vinculo

    def _fingir_que_no_existe(*args, **kwargs):
        original(*args, **kwargs)
        return None

    escritor.registrar_vinculo("alt-carrera-par", "pid-1")  # "otro proceso" ya escribió
    escritor._buscar_vinculo = _fingir_que_no_existe
    try:
        escritor.registrar_vinculo("alt-carrera-par", "pid-1")  # no debe propagar IntegrityError
    finally:
        escritor._buscar_vinculo = original

    filas = _leer_todas(motor, VinculoPaciente)
    assert len(filas) == 1
    assert filas[0].id_paciente == "pid-1"
    assert filas[0].ambiguo is False


def test_registrar_vinculo_resiste_una_carrera_con_homonimo_real(escritor: EscritorPostgres, motor) -> None:
    """La carrera NO puede tapar un homónimo real: si el que ganó insertó un
    `id_paciente` DISTINTO, el invariante "una vez ambiguo, siempre ambiguo"
    tiene que activarse igual -- perderlo acá sería afirmar en silencio que
    dos pacientes distintos son el mismo."""
    original = escritor._buscar_vinculo

    def _fingir_que_no_existe(*args, **kwargs):
        original(*args, **kwargs)
        return None

    escritor.registrar_vinculo("alt-carrera-homonimo", "pid-A")  # "otro proceso" ganó la carrera
    escritor._buscar_vinculo = _fingir_que_no_existe
    try:
        escritor.registrar_vinculo("alt-carrera-homonimo", "pid-B")  # homónimo real
    finally:
        escritor._buscar_vinculo = original

    filas = _leer_todas(motor, VinculoPaciente)
    assert len(filas) == 1
    assert filas[0].id_paciente is None
    assert filas[0].ambiguo is True


def test_escribir_episodio_resiste_una_carrera(escritor: EscritorPostgres, motor) -> None:
    """Dos procesos escriben el mismo episodio a la vez: `id_episodio` es
    función pura de `(id_paciente, fecha_ancla)`, así que no hay nada que
    decidir -- tratar "ya existe" como éxito alcanza."""
    original = escritor._buscar_episodio

    def _fingir_que_no_existe(*args, **kwargs):
        original(*args, **kwargs)
        return None

    escritor.escribir_episodio(id_episodio="ep-carrera", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10))
    escritor._buscar_episodio = _fingir_que_no_existe
    try:
        escritor.escribir_episodio(
            id_episodio="ep-carrera", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10)
        )  # no debe propagar IntegrityError
    finally:
        escritor._buscar_episodio = original

    assert len(_leer_todas(motor, Episodio)) == 1


# --- construir_engine_postgres: pool contra RDS (paralelismo-de-procesamiento) --
#
# `pool_pre_ping`/`pool_recycle` importan sólo contra una base de red real
# (RDS puede cerrar una conexión ociosa del pool sin avisar); estos tests
# verifican la CONFIGURACIÓN del engine, no requieren conexión real -- crear
# un `Engine` con SQLAlchemy es perezoso, no abre socket hasta el primer uso.


def test_construir_engine_postgres_activa_pre_ping_y_recycle_explicito() -> None:
    engine = construir_engine_postgres("postgresql+psycopg://usuario:clave@localhost/base")
    try:
        assert engine.pool._pre_ping is True
        assert engine.pool._recycle == POOL_RECYCLE_SEGUNDOS
        assert engine.pool.size() == POOL_SIZE
    finally:
        engine.dispose()


def test_construir_engine_postgres_no_rompe_con_sqlite(motor) -> None:
    """SQLite no tiene pool de red: la config se acepta pero no representa nada
    real -- `pool_size` lo ignora `SingletonThreadPool`, sin error ni warning."""
    engine = construir_engine_postgres("sqlite:///:memory:")
    try:
        with sa.orm.Session(engine) as sesion:
            sesion.execute(sa.text("SELECT 1"))
    finally:
        engine.dispose()


def test_construir_engine_postgres_fija_un_timeout_de_conexion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Revisión adversarial, CRÍTICO 3 -- reproducido a mano: sin
    `connect_args={"connect_timeout": ...}`, un host que no responde deja a
    `construir_engine_postgres` colgado varios minutos (handshake TCP/TLS
    de psycopg sin tope), con la terminal del operador congelada y sin
    ningún mensaje. Se verifica que el argumento viaje hasta
    `sqlalchemy.create_engine` -- no se reproduce acá el cuelgue real (la
    suite bloquea toda conexión de red real, `tests/conftest.py`); esa
    verificación se hizo a mano contra un puerto cerrado, ver el reporte."""
    capturado: dict[str, object] = {}
    original_create_engine = destinos_postgres.create_engine

    def _espia(url: str, **kwargs: object):
        capturado.update(kwargs)
        return original_create_engine(url, **kwargs)

    monkeypatch.setattr(destinos_postgres, "create_engine", _espia)

    engine = construir_engine_postgres("postgresql+psycopg://usuario:clave@host-cualquiera:5433/db")
    engine.dispose()

    assert "connect_args" in capturado, "connect_args no llegó a create_engine -- sin timeout de conexión"
    assert capturado["connect_args"]["connect_timeout"] > 0


def test_construir_engine_postgres_no_le_pasa_connect_timeout_a_sqlite(motor) -> None:
    """SQLite no entiende `connect_timeout` (su DBAPI usa `timeout`, otro
    nombre) -- pasarlo igual rompería CUALQUIER uso de este módulo con
    SQLite en la suite entera (todos los tests de este archivo). El timeout
    de conexión sólo tiene sentido -- y sólo se agrega -- para el dialecto
    `postgresql`."""
    engine = construir_engine_postgres("sqlite:///:memory:")
    try:
        with sa.orm.Session(engine) as sesion:
            sesion.execute(sa.text("SELECT 1"))
    finally:
        engine.dispose()

