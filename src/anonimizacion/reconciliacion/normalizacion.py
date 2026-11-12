"""Normalizaciones explícitas que nunca alteran significado clínico."""

from __future__ import annotations

from datetime import datetime
import re

from anonimizacion.dominio.precision_hora import PrecisionHora

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


def normalizar_hora_iso(valor: str) -> tuple[str, PrecisionHora]:
    """Convierte formatos de hora explícitos (`%H:%M:%S`/`%H:%M`), sin inferir husos.
    Rechaza horas sin cero a la izquierda (p. ej. `"8:45"`): formato no confirmado contra muestras."""
    candidato = valor.strip()
    for formato, precision in (
        ("%H:%M:%S", PrecisionHora.SEGUNDO),
        ("%H:%M", PrecisionHora.MINUTO),
    ):
        try:
            hora = datetime.strptime(candidato, formato)
        except ValueError:
            continue
        if hora.strftime(formato) != candidato:
            continue  # p. ej. "8:45" sin cero a la izquierda -- ver docstring
        return candidato, precision
    raise ValueError("hora no permitida")
