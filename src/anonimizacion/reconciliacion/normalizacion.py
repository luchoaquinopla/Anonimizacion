"""Normalizaciones explícitas que nunca alteran significado clínico."""

from __future__ import annotations

from datetime import datetime
import re

_ESPACIOS = re.compile(r"\s+")
_NUMERO = re.compile(r"\d+(?:[,.]\d+)?")


def normalizar_texto(valor: str) -> str:
    """Colapsa espacios, separadores estructurales y mayúsculas."""
    return _ESPACIOS.sub(" ", valor.replace("|", " ")).strip().casefold()


def normalizar_numero(valor: str, *, decimales_permitidos: int | None = None) -> str:
    """Acepta solo una representación numérica sin unidad, signo o conversión."""
    candidato = valor.strip()
    if not _NUMERO.fullmatch(candidato):
        raise ValueError("número no permitido")

    normalizado = candidato.replace(",", ".")
    decimales = normalizado.partition(".")[2]
    if decimales_permitidos is not None and len(decimales) > decimales_permitidos:
        raise ValueError("precisión no permitida")
    return normalizado


def normalizar_fecha_iso(valor: str) -> str:
    """Convierte formatos de fecha explícitos a ISO, sin inferir fechas."""
    candidato = valor.strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(candidato, formato).date().isoformat()
        except ValueError:
            continue
    raise ValueError("fecha no permitida")
