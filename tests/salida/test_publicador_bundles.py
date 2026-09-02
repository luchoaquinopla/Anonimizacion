from __future__ import annotations

import json
from datetime import date

import pyarrow.parquet as pq

from anonimizacion.dominio.modelos import RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.salida.destinos.parquet import EscritorParquet
from anonimizacion.salida.publicador_bundles import PublicadorBundles

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"


def _clave(semilla: str) -> str:
    sha256_sintetico = (semilla * 64)[:64]  # huella inventada, ningún valor real
    return generar_clave_documento(PEPPER_TEST, sha256_sintetico)


def _registro(
    tipo_documento: TipoDocumento = TipoDocumento.ECG,
    clave_documento: str | None = None,
) -> RegistroAnonimizado:
    return RegistroAnonimizado(
        id_paciente="pid-seguro",
        id_episodio="ep-seguro",
        tipo_documento=tipo_documento,
        version_esquema=1,
        fecha_estudio=date(2024, 1, 1),
        contenido=None,
        clave_documento=clave_documento,
    )


def test_publicador_escribe_bundle_atomico_sin_pii_en_manifiesto(tmp_path) -> None:
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))

    ruta = publicador.publicar([_registro()], version_pipeline="v1")

    manifiesto = (ruta / "manifest.json").read_text(encoding="utf8")
    assert ruta == tmp_path / "pid-seguro" / "ep-seguro"
    assert "pid-seguro" in manifiesto
    assert "nombre" not in manifiesto.lower()
    assert not list(tmp_path.rglob("*.tmp"))


def test_parquet_de_episodio_con_un_solo_documento_republicado_sigue_teniendo_una_fila(tmp_path) -> None:
    """Firma nueva de `escribir_episodio` (Fase 7, spec `escritura-idempotente`):
    recibe la secuencia completa, no un registro por llamada. Reemplaza al
    test homónimo que fijaba el bug de sobrescritura como comportamiento
    correcto (docstring original: "mantiene una sola fila vigente" para un
    episodio de VARIOS documentos, que era exactamente el defecto). Con un
    solo documento, escribir dos veces sigue dejando una fila -- eso sí es
    correcto, y queda cubierto además por
    `test_escribir_episodio_con_secuencia_completa_conserva_los_tres_documentos`
    en `tests/salida/destinos/test_parquet.py`."""
    escritor = EscritorParquet(tmp_path)
    registro = _registro()

    escritor.escribir_episodio([registro])
    escritor.escribir_episodio([registro])

    tabla = pq.read_table(tmp_path / "episodios" / "ep-seguro.parquet")
    assert tabla.num_rows == 1


# --- Fase 8: guarda por documento, no por directorio (spec escritura-idempotente) --


def test_publicar_episodio_de_tres_estudios_conserva_los_tres(tmp_path) -> None:
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))
    registros = [
        _registro(TipoDocumento.ECG, _clave("ecg")),
        _registro(TipoDocumento.LABORATORIO, _clave("lab")),
        _registro(TipoDocumento.ECOCARDIOGRAMA, _clave("eco")),
    ]

    ruta = publicador.publicar(registros, version_pipeline="v1")

    tabla = pq.read_table(tmp_path / "analitico" / "episodios" / "ep-seguro.parquet")
    assert tabla.num_rows == 3
    manifiesto = json.loads((ruta / "manifest.json").read_text(encoding="utf8"))
    assert set(manifiesto["tipos_documento"]) == {
        TipoDocumento.ECG.value,
        TipoDocumento.LABORATORIO.value,
        TipoDocumento.ECOCARDIOGRAMA.value,
    }


def test_republicar_mismo_episodio_es_byte_a_byte_identico(tmp_path) -> None:
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))
    registros = [_registro(TipoDocumento.ECG, _clave("ecg")), _registro(TipoDocumento.LABORATORIO, _clave("lab"))]

    ruta_1 = publicador.publicar(registros, version_pipeline="v1")
    manifiesto_1 = (ruta_1 / "manifest.json").read_bytes()
    mtime_1 = (ruta_1 / "manifest.json").stat().st_mtime_ns
    tabla_1 = (tmp_path / "analitico" / "episodios" / "ep-seguro.parquet").read_bytes()

    ruta_2 = publicador.publicar(registros, version_pipeline="v1")
    manifiesto_2 = (ruta_2 / "manifest.json").read_bytes()
    mtime_2 = (ruta_2 / "manifest.json").stat().st_mtime_ns
    tabla_2 = (tmp_path / "analitico" / "episodios" / "ep-seguro.parquet").read_bytes()

    assert manifiesto_1 == manifiesto_2
    assert mtime_1 == mtime_2  # no se reescribió: sin novedades, no se toca nada
    assert tabla_1 == tabla_2


def test_republicar_con_documento_adicional_agrega_el_que_faltaba(tmp_path) -> None:
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))
    registros_parciales = [_registro(TipoDocumento.ECG, _clave("ecg")), _registro(TipoDocumento.LABORATORIO, _clave("lab"))]

    publicador.publicar(registros_parciales, version_pipeline="v1")

    registros_completos = registros_parciales + [_registro(TipoDocumento.ECOCARDIOGRAMA, _clave("eco"))]
    ruta = publicador.publicar(registros_completos, version_pipeline="v1")

    manifiesto = json.loads((ruta / "manifest.json").read_text(encoding="utf8"))
    assert len(manifiesto["documentos"]) == 3
    tabla = pq.read_table(tmp_path / "analitico" / "episodios" / "ep-seguro.parquet")
    assert tabla.num_rows == 3


def test_republicar_sin_novedades_no_reescribe_el_manifiesto(tmp_path) -> None:
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))
    registros = [_registro(TipoDocumento.ECG, _clave("ecg"))]

    ruta = publicador.publicar(registros, version_pipeline="v1")
    mtime_antes = (ruta / "manifest.json").stat().st_mtime_ns

    publicador.publicar(registros, version_pipeline="v1")
    mtime_despues = (ruta / "manifest.json").stat().st_mtime_ns

    assert mtime_antes == mtime_despues


def test_registro_sin_clave_documento_se_trata_como_siempre_nuevo(tmp_path) -> None:
    """8.8: un registro con `clave_documento=None` no participa de la dedup
    (mismo criterio NULL-no-colisiona), pero tampoco rompe la guarda -- se
    trata como novedad, y el manifiesto/Parquet se reescriben."""
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))
    registro_sin_clave = _registro(TipoDocumento.ECG, clave_documento=None)

    ruta_1 = publicador.publicar([registro_sin_clave], version_pipeline="v1")
    ruta_2 = publicador.publicar([registro_sin_clave], version_pipeline="v1")

    assert ruta_1 == ruta_2
    manifiesto = json.loads((ruta_2 / "manifest.json").read_text(encoding="utf8"))
    assert manifiesto["documentos"] == []  # None no se registra como identidad


def test_publicar_lote_vacio_sigue_lanzando_value_error(tmp_path) -> None:
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))
    import pytest

    with pytest.raises(ValueError):
        publicador.publicar([], version_pipeline="v1")


def test_publicar_episodios_mezclados_sigue_lanzando_value_error(tmp_path) -> None:
    publicador = PublicadorBundles(tmp_path, EscritorParquet(tmp_path / "analitico"))
    import pytest

    otro_episodio = RegistroAnonimizado(
        id_paciente="pid-seguro",
        id_episodio="otro-episodio",
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        fecha_estudio=date(2024, 1, 1),
        contenido=None,
    )

    with pytest.raises(ValueError):
        publicador.publicar([_registro(), otro_episodio], version_pipeline="v1")
