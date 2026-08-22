"""Publicación atómica de bundles anonimizados por episodio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from anonimizacion.dominio.modelos import RegistroAnonimizado
from anonimizacion.salida.destinos.parquet import EscritorParquet


class PublicadorBundles:
    def __init__(self, directorio_base: Path, escritor_parquet: EscritorParquet) -> None:
        self._directorio_base = Path(directorio_base)
        self._escritor_parquet = escritor_parquet

    def publicar(self, registros: Sequence[RegistroAnonimizado], *, version_pipeline: str) -> Path:
        if not registros:
            raise ValueError("un bundle requiere al menos un registro")
        primero = registros[0]
        if any(registro.id_paciente != primero.id_paciente or registro.id_episodio != primero.id_episodio for registro in registros):
            raise ValueError("todos los registros deben pertenecer al mismo episodio")

        destino = self._directorio_base / primero.id_paciente / primero.id_episodio
        if not destino.exists():
            temporal = destino.with_name(f".{destino.name}.tmp")
            temporal.mkdir(parents=True, exist_ok=False)
            manifiesto = {
                "id_paciente": primero.id_paciente,
                "id_episodio": primero.id_episodio,
                "version_pipeline": version_pipeline,
                "tipos_documento": sorted(registro.tipo_documento.value for registro in registros),
            }
            (temporal / "manifest.json").write_text(json.dumps(manifiesto, sort_keys=True), encoding="utf8")
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporal.replace(destino)
        for registro in registros:
            self._escritor_parquet.escribir_episodio(registro)
        return destino
