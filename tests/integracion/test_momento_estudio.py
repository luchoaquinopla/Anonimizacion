"""El momento del estudio sobrevive idéntico a Postgres (spec `momento-del-estudio`).

La prueba que importa acá no es que la hora se guarde, sino que **la ausencia se
guarde como ausencia**. Un ecocardiograma no trae hora; si en algún tramo del
camino recibiera un default de medianoche, ese valor sería después
indistinguible de una hora real y contaminaría exactamente el análisis temporal
que motivó el cambio.

Se verifica contra Postgres (SQLite en memoria, ver `tests/salida/`).

Nota (`chore/resolver-codigo-desconectado`): este archivo se llamaba
`test_momento_estudio_ambos_destinos.py` y verificaba también el dataset
Parquet (`EscritorParquet`). Se quitó esa mitad al eliminar `destinos/parquet.py`
y `publicador_bundles.py` -- no tenían llamador de producción. Ver
`docs/pipeline.md` para el destino de Postgres como única salida.
"""
from __future__ import annotations

from datetime import date, time

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
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.salida.constructor_registro import construir_registro
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
        construir_registro(
            documento,
            claves,
            id_episodio="ep-1",
            pepper=_PEPPER,
            clave_documento=generar_clave_documento(_PEPPER, f"sha-sintetico-{indice}".ljust(64, "0")),
        )
        for indice, documento in enumerate(documentos)
    )


@pytest.fixture()
def motor():
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def test_hora_y_precision_llegan_iguales_a_postgres(motor) -> None:
    escritor_sql = EscritorPostgres(motor)
    escritor_sql.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=_FECHA)

    registros = _registros()
    for registro in registros:
        escritor_sql.escribir_registro(registro)

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


def test_la_ausencia_es_distinguible_de_una_hora_real(motor) -> None:
    """Si `AUSENTE` se persistiera como `00:00:00`, este test lo detecta."""
    escritor_sql = EscritorPostgres(motor)
    escritor_sql.escribir_episodio(id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=_FECHA)

    registros = _registros()
    for registro in registros:
        escritor_sql.escribir_registro(registro)

    with Session(motor) as sesion:
        horas_ausentes = sesion.scalars(
            sa.select(Estudio.hora_estudio).where(Estudio.precision_hora == "ausente")
        ).all()
    assert list(horas_ausentes) == [None]
