"""Tests de `salida/destinos/parquet.py` (tasks.md 7.4, design.md decisión Q1: Parquet como capa de consumo).

`EscritorParquet` es la capa de EXPORT/consumo para el pipeline de DL --
"derivada de Postgres, no la fuente de verdad" (design.md). Recibe
`RegistroAnonimizado` ya construidos (mismo tipo que `EscritorPostgres`) y
los particiona en `directorio_base/<tipo_documento>/anio=<año>/*.parquet`,
un subárbol por `tipo_documento` porque cada uno tiene columnas distintas
(ancha para ECG/eco, larga/EAV para laboratorio) -- no tiene sentido un
único esquema Parquet para los tres.
"""

from __future__ import annotations

from datetime import date, time

import pyarrow.parquet as pq
import pytest
from pydantic import SecretStr

from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.parseo.eco_doppler import ContenidoEco, FirmaMedico, MedidaEco, SeccionTextoEco
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio, ResultadoLaboratorio
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.salida.constructor_registro import construir_registro
from anonimizacion.salida.destinos.parquet import EscritorParquet

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"
CLAVES_TEST = ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1)


def _clave_documento_sintetica(semilla: str) -> str:
    # huella inventada, distinta por `semilla` -- suficiente para tests, nunca un sha256 real
    sha256_sintetico = (semilla * 64)[:64]
    return generar_clave_documento(PEPPER_TEST, sha256_sintetico)


def _registro_laboratorio(
    fecha: date, id_episodio: str, clave_documento: str | None = None
) -> "RegistroAnonimizado":  # noqa: F821
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=fecha,
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
        adicionales={},
    )
    clave = clave_documento or _clave_documento_sintetica(f"lab-{id_episodio}")
    return construir_registro(documento, CLAVES_TEST, id_episodio=id_episodio, pepper=PEPPER_TEST, clave_documento=clave)


def _registro_ecg(
    fecha: date, id_episodio: str, clave_documento: str | None = None
) -> "RegistroAnonimizado":  # noqa: F821
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=fecha,
        contenido=ContenidoEcg(vent_rate="72", pr_interval="160", qrs_duration="90", qt_qtc="400/420", ejes="P60 R30 T40"),
        adicionales={},
    )
    clave = clave_documento or _clave_documento_sintetica(f"ecg-{id_episodio}")
    return construir_registro(documento, CLAVES_TEST, id_episodio=id_episodio, pepper=PEPPER_TEST, clave_documento=clave)


def _registro_eco(
    fecha: date, id_episodio: str, clave_documento: str | None = None
) -> "RegistroAnonimizado":  # noqa: F821
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=fecha,
        contenido=ContenidoEco(
            medidas=(MedidaEco(nombre="AO", valor="28", unidad="mm"),),
            secciones_texto=(SeccionTextoEco(nombre="CONCLUSIONES", texto="Sin hallazgos"),),
            firma=FirmaMedico(nombre="Dr. Carlos Gomez", matricula="MP12345"),
        ),
        adicionales={},
    )
    clave = clave_documento or _clave_documento_sintetica(f"eco-{id_episodio}")
    return construir_registro(documento, CLAVES_TEST, id_episodio=id_episodio, pepper=PEPPER_TEST, clave_documento=clave)


def test_escribir_laboratorio_particiona_por_tipo_documento_y_anio(tmp_path) -> None:
    escritor = EscritorParquet(tmp_path)
    registro_2023 = _registro_laboratorio(date(2023, 12, 20), "ep-2023")
    registro_2024 = _registro_laboratorio(date(2024, 1, 10), "ep-2024")

    escritor.escribir([registro_2023, registro_2024])

    tabla = pq.read_table(tmp_path / "laboratorio")
    filas = tabla.to_pylist()
    assert {fila["anio"] for fila in filas} == {2023, 2024}
    assert {fila["analito"] for fila in filas} == {"Hemoglobina"}
    assert (tmp_path / "laboratorio" / "anio=2023").exists()
    assert (tmp_path / "laboratorio" / "anio=2024").exists()


def test_escribir_ecg_particiona_por_anio_con_columnas_anchas(tmp_path) -> None:
    escritor = EscritorParquet(tmp_path)
    escritor.escribir([_registro_ecg(date(2024, 3, 1), "ep-1")])

    tabla = pq.read_table(tmp_path / "ecg")
    filas = tabla.to_pylist()
    assert len(filas) == 1
    assert filas[0]["vent_rate"] == "72"
    assert filas[0]["anio"] == 2024


def test_escribir_eco_genera_dataset_de_medidas_y_de_texto_libre(tmp_path) -> None:
    escritor = EscritorParquet(tmp_path)
    escritor.escribir([_registro_eco(date(2024, 5, 5), "ep-1")])

    tabla_medidas = pq.read_table(tmp_path / "eco_medidas")
    tabla_texto = pq.read_table(tmp_path / "eco_texto")

    assert tabla_medidas.to_pylist()[0]["nombre"] == "AO"
    assert tabla_texto.to_pylist()[0]["texto"] == "Sin hallazgos"


def test_escribir_lote_solo_de_eco_declara_tipo_explicito_de_hora_estudio(tmp_path) -> None:
    """Gotcha 4 (design.md, decisión 3): `pa.Table.from_pylist` infiere el
    tipo de columna por lote -- un lote compuesto ENTERAMENTE por
    ecocardiogramas (todos con `hora_estudio=None`, `precision_hora=AUSENTE`)
    dejaría la columna `hora_estudio` con tipo `null` inferido, que choca al
    leer un dataset combinado con la partición de ECG (que sí trae strings).
    Debe declarar un tipo string explícito incluso cuando todos los valores
    son `None`."""
    import pyarrow as pa

    escritor = EscritorParquet(tmp_path)
    escritor.escribir([_registro_eco(date(2024, 5, 5), "ep-1"), _registro_eco(date(2024, 5, 6), "ep-2")])

    tabla_medidas = pq.read_table(tmp_path / "eco_medidas")
    tabla_texto = pq.read_table(tmp_path / "eco_texto")

    assert tabla_medidas.schema.field("hora_estudio").type == pa.string()
    assert tabla_texto.schema.field("hora_estudio").type == pa.string()
    assert all(valor is None for valor in tabla_medidas.column("hora_estudio").to_pylist())


def test_dataset_combinado_ecg_y_eco_no_choca_por_tipo_de_columna_hora(tmp_path) -> None:
    """REFACTOR de la Fase 10: lee de vuelta un dataset con partición de ECG
    (hora_estudio con valor real) y confirma que declarar el schema explícito
    no rompe la lectura normal cuando SÍ hay valores no nulos."""
    escritor = EscritorParquet(tmp_path)
    escritor.escribir([_registro_ecg(date(2024, 3, 1), "ep-1")])

    tabla = pq.read_table(tmp_path / "ecg")
    filas = tabla.to_pylist()

    assert filas[0]["hora_estudio"] is None  # el builder de este test no fija hora_estudio
    assert filas[0]["precision_hora"] == "ausente"


def test_precision_hora_distingue_valores_de_hora_byte_a_byte_identicos(tmp_path) -> None:
    """Gotcha 3 (design.md, decisión 3): un laboratorio a las `08:45` (precisión
    `MINUTO`) se persiste `08:45:00`, byte a byte idéntico a un ECG cuyo header
    dijera esa misma hora (precisión `SEGUNDO`). `precision_hora` es lo único
    que distingue ambos casos -- no es derivable del valor de `hora_estudio`."""
    resultado_con_fila = ContenidoLaboratorio(
        numero_peticion="P-1",
        resultados=(
            ResultadoLaboratorio(
                seccion="HEMATOLOGIA", prueba="Hemoglobina", resultado="14.5",
                unidades="g/dL", valores_referencia="12-16",
            ),
        ),
    )
    registro_lab = construir_registro(
        DocumentoParseado(
            tipo_documento=TipoDocumento.LABORATORIO,
            version_esquema=1,
            identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
            fecha_estudio=date(2024, 1, 10),
            hora_estudio=time(8, 45),
            precision_hora=PrecisionHora.MINUTO,
            contenido=resultado_con_fila,
        ),
        CLAVES_TEST,
        id_episodio="ep-lab",
        pepper=PEPPER_TEST,
        clave_documento=_clave_documento_sintetica("lab-ep-lab"),
    )
    documento_ecg = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        hora_estudio=time(8, 45, 0),
        precision_hora=PrecisionHora.SEGUNDO,
        contenido=ContenidoEcg(vent_rate="72", pr_interval=None, qrs_duration=None, qt_qtc=None, ejes=None),
    )
    registro_ecg = construir_registro(
        documento_ecg,
        CLAVES_TEST,
        id_episodio="ep-ecg",
        pepper=PEPPER_TEST,
        clave_documento=_clave_documento_sintetica("ecg-ep-ecg"),
    )

    escritor = EscritorParquet(tmp_path)
    escritor.escribir([registro_lab, registro_ecg])

    fila_lab = pq.read_table(tmp_path / "laboratorio").to_pylist()[0]
    fila_ecg = pq.read_table(tmp_path / "ecg").to_pylist()[0]

    assert fila_lab["hora_estudio"] == fila_ecg["hora_estudio"] == "08:45:00"
    assert fila_lab["precision_hora"] == "minuto"
    assert fila_ecg["precision_hora"] == "segundo"


def test_escribir_lista_vacia_no_falla(tmp_path) -> None:
    escritor = EscritorParquet(tmp_path)
    escritor.escribir([])  # no debe crear datasets ni lanzar


def test_escribir_tipo_no_reconocido_lanza_value_error(tmp_path) -> None:
    from anonimizacion.dominio.modelos import RegistroAnonimizado

    escritor = EscritorParquet(tmp_path)
    registro_invalido = RegistroAnonimizado(
        id_paciente="pid-1",
        id_episodio="ep-1",
        tipo_documento=TipoDocumento.TIPO_NO_RECONOCIDO,
        version_esquema=1,
        fecha_estudio=date(2024, 1, 1),
        contenido=None,
    )

    with pytest.raises(ValueError):
        escritor.escribir([registro_invalido])
