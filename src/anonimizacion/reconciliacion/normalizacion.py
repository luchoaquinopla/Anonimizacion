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
    """Convierte formatos de hora explícitos, sin inferir husos ni completar valores.

    Espejo de `normalizar_fecha_iso`: prueba `%H:%M:%S` (precisión `SEGUNDO`)
    y `%H:%M` (precisión `MINUTO`) en ese orden, levanta `ValueError` si
    ninguno matchea.

    Decisión (Fase 2.1 de `openspec/changes/hora-de-estudio/tasks.md`, dejada
    abierta por las tareas): rechaza horas sin cero a la izquierda (p. ej.
    `"8:45"`). `datetime.strptime` por sí solo es laxo con eso y aceptaría
    `"8:45"` igual que `"08:45"` -- se agrega un chequeo de ida y vuelta
    (`strftime(formato) == candidato`) para exigir el formato exacto de dos
    dígitos. El layout real calibrado contra las muestras (ECG `HH:MM:SS`,
    laboratorio `Hora de Extracción: HH:MM`) siempre trae dos dígitos; dado
    el principio de "cero inferencia" que ya aplica `normalizar_fecha_iso`,
    rechazar un formato no confirmado es más seguro que aceptarlo de más.
    """
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
