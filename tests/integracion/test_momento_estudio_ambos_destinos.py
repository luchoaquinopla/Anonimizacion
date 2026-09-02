"""El momento del estudio sobrevive idéntico a los dos destinos (spec `momento-del-estudio`).

La prueba que importa acá no es que la hora se guarde, sino que **la ausencia se
guarde como ausencia**. Un ecocardiograma no trae hora; si en algún tramo del
camino recibiera un default de medianoche, ese valor sería después
indistinguible de una hora real y contaminaría exactamente el análisis temporal
que motivó el cambio.

Se verifica contra Postgres (SQLite en memoria, ver `tests/salida/`) y contra
Parquet en el mismo test, porque el riesgo es justamente que un destino
represente la ausencia distinto del otro.
"""
from __future__ import annotations

from datetime import date, time

import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.orm import Session

from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.parseo.eco_doppler import ContenidoEco, MedidaEco
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio, ResultadoLaboratorio
from anonimizacion.salida.constructor_registro import construir_registro
from anonimizacion.salida.destinos.parquet import EscritorParquet
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base, Estudio

_PEPPER = b"pepper-fijo-de-test-nunca-real"
_FECHA = date(2024, 5, 20)


def _documento(tipo: TipoDocumento, contenido, hora: time | None, precision: PrecisionHora):
    return DocumentoParseado(
        tipo_documento=tipo,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Nombre Sintetico")),
        fecha_estudio=_FECHA,
        hora_estudio=hora,
        precision_hora=precision,
        contenido=contenido,
    )


def _registros():
    claves = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)
    documentos = (
        # ECG: hora al segundo.
        _documento(
            TipoDocumento.ECG,
            ContenidoEcg(
                vent_rate="73", pr_interval="186", qrs_duration="100", qt_qtc="382/420", ejes="63 51 26"
            ),
            time(15, 17, 59),
            PrecisionHora.SEGUNDO,
        ),
        # Laboratorio: hora de extracción, precisión de minuto.
        _documento(
            TipoDocumento.LABORATORIO,
            ContenidoLaboratorio(
                numero_peticion="P-1",
                resultados=(
                    ResultadoLaboratorio(
                        seccion="IONOGRAMA",
                        prueba="Potasio",
                        resultado="3.9",
                        unidades="meq/lt",
                        valores_referencia="3.5 - 5.0",
                    ),
                ),
            ),
            time(8, 24),
            PrecisionHora.MINUTO,
        ),
        # Eco: el documento no trae hora. Ausencia explícita.
        _documento(
            TipoDocumento.ECOCARDIOGRAMA,
            ContenidoEco(
                medidas=(MedidaEco(nombre="AO", valor="36", unidad="mm"),),
                secciones_texto=(),
                firma=None,
            ),
            None,
            PrecisionHora.AUSENTE,
        ),
    )
    return tuple(
        construir_registro(documento, claves, id_episodio="ep-1", pepper=_PEPPER)
        for documento in documentos
    )


@pytest.fixture()
def motor():
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def test_hora_y_precision_llegan_iguales_a_postgres_y_a_parquet(motor, tmp_path) -> None:
    escritor_sql = EscritorPostgres(motor)
    escritor_sql.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=_FECHA)
    escritor_parquet = EscritorParquet(tmp_path)

    registros = _registros()
    for registro in registros:
        escritor_sql.escribir_registro(registro)
    escritor_parquet.escribir(list(registros))

    # --- destino SQL ---
    with Session(motor) as sesion:
        estudios = {
            estudio.tipo_documento: estudio for estudio in sesion.scalars(sa.select(Estudio)).all()
        }

    assert estudios[TipoDocumento.ECG.value].hora_estudio == time(15, 17, 59)
    assert estudios[TipoDocumento.ECG.value].precision_hora == "segundo"
    assert estudios[TipoDocumento.LABORATORIO.value].hora_estudio == time(8, 24)
    assert estudios[TipoDocumento.LABORATORIO.value].precision_hora == "minuto"
    assert estudios[TipoDocumento.ECOCARDIOGRAMA.value].hora_estudio is None
    assert estudios[TipoDocumento.ECOCARDIOGRAMA.value].precision_hora == "ausente"

    # --- destino Parquet ---
    # Cada tipo va a su propio dataset con su propio schema: se leen por separado.
    por_precision: dict[str, set] = {}
    for dataset in ("ecg", "laboratorio", "eco_medidas"):
        tabla = pq.read_table(tmp_path / dataset)
        assert "hora_estudio" in tabla.column_names
        assert "precision_hora" in tabla.column_names
        for fila in tabla.to_pylist():
            por_precision.setdefault(fila["precision_hora"], set()).add(fila["hora_estudio"])

    assert por_precision["segundo"] == {"15:17:59"}
    assert por_precision["minuto"] == {"08:24:00"}
    # La ausencia nunca se materializa como medianoche.
    assert por_precision["ausente"] == {None}


def test_la_ausencia_es_distinguible_de_una_hora_real_en_ambos_destinos(motor, tmp_path) -> None:
    """Si `AUSENTE` se persistiera como `00:00:00`, este test lo detecta."""
    escritor_sql = EscritorPostgres(motor)
    escritor_sql.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=_FECHA)
    escritor_parquet = EscritorParquet(tmp_path)

    registros = _registros()
    for registro in registros:
        escritor_sql.escribir_registro(registro)
    escritor_parquet.escribir(list(registros))

    with Session(motor) as sesion:
        horas_ausentes = sesion.scalars(
            sa.select(Estudio.hora_estudio).where(Estudio.precision_hora == "ausente")
        ).all()
    assert list(horas_ausentes) == [None]

    horas_parquet = {
        fila["hora_estudio"]
        for dataset in ("ecg", "laboratorio", "eco_medidas")
        for fila in pq.read_table(tmp_path / dataset).to_pylist()
        if fila["precision_hora"] == "ausente"
    }
    assert horas_parquet == {None}
    assert "00:00:00" not in horas_parquet
