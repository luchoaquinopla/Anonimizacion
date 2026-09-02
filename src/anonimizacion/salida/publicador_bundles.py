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
        """Publica el bundle del episodio; guarda por `clave_documento`, no por directorio.

        La guarda anterior era por directorio: un episodio republicado con un
        documento más no reescribía nada porque el directorio ya existía, y el
        manifiesto quedaba describiendo un bundle que ya no coincidía con lo
        publicado. Ahora se lee el manifiesto existente (si lo hay) y se
        compara `clave_documento` contra `documentos`: sin novedades, no se
        toca nada (ni manifiesto ni Parquet); con novedades, se reescribe la
        UNIÓN atómicamente y se regenera la proyección Parquet del episodio
        con la secuencia completa recibida (spec `escritura-idempotente`,
        Requisitos 4 y 5).

        Un registro con `clave_documento is None` se trata como "siempre
        nuevo" -- dispara la reescritura, pero no se registra en `documentos`
        (mismo criterio NULL-no-colisiona que Postgres: no hay identidad que
        anotar).
        """
        if not registros:
            raise ValueError("un bundle requiere al menos un registro")
        primero = registros[0]
        if any(registro.id_paciente != primero.id_paciente or registro.id_episodio != primero.id_episodio for registro in registros):
            raise ValueError("todos los registros deben pertenecer al mismo episodio")

        destino = self._directorio_base / primero.id_paciente / primero.id_episodio
        manifiesto_existente = self._leer_manifiesto(destino)
        documentos_existentes = tuple(manifiesto_existente["documentos"]) if manifiesto_existente else ()

        claves_actuales = [registro.clave_documento for registro in registros if registro.clave_documento is not None]
        hay_clave_nueva = any(clave not in documentos_existentes for clave in claves_actuales)
        hay_registro_sin_clave = any(registro.clave_documento is None for registro in registros)
        hay_novedades = manifiesto_existente is None or hay_clave_nueva or hay_registro_sin_clave

        if not hay_novedades:
            return destino

        documentos_union = sorted(set(documentos_existentes) | set(claves_actuales))
        tipos_existentes = set(manifiesto_existente["tipos_documento"]) if manifiesto_existente else set()
        tipos_union = sorted(tipos_existentes | {registro.tipo_documento.value for registro in registros})

        manifiesto = {
            "id_paciente": primero.id_paciente,
            "id_episodio": primero.id_episodio,
            "version_pipeline": version_pipeline,
            "tipos_documento": tipos_union,
            "documentos": documentos_union,
        }
        self._escribir_manifiesto_atomico(destino, manifiesto)
        self._escritor_parquet.escribir_episodio(registros)
        return destino

    @staticmethod
    def _leer_manifiesto(destino: Path) -> dict | None:
        ruta = destino / "manifest.json"
        if not ruta.exists():
            return None
        return json.loads(ruta.read_text(encoding="utf8"))

    @staticmethod
    def _escribir_manifiesto_atomico(destino: Path, manifiesto: dict) -> None:
        destino.mkdir(parents=True, exist_ok=True)
        temporal = destino / ".manifest.json.tmp"
        temporal.write_text(json.dumps(manifiesto, sort_keys=True), encoding="utf8")
        temporal.replace(destino / "manifest.json")
