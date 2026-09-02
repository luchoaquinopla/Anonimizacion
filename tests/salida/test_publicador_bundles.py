from __future__ import annotations

from datetime import date

import pyarrow.parquet as pq

from anonimizacion.dominio.modelos import RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.salida.destinos.parquet import EscritorParquet
from anonimizacion.salida.publicador_bundles import PublicadorBundles


def _registro() -> RegistroAnonimizado:
    return RegistroAnonimizado(
        id_paciente="pid-seguro",
        id_episodio="ep-seguro",
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        fecha_estudio=date(2024, 1, 1),
        contenido=None,
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
