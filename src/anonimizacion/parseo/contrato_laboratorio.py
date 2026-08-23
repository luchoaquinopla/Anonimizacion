"""Reglas estructurales compartidas del layout de laboratorio."""

from __future__ import annotations

import re


SECCIONES_LABORATORIO = frozenset(
    {"HEMATOLOGIA", "HEMOSTASIA", "QUIMICA CLINICA", "IONOGRAMA"}
)

_ALIAS_SECCIONES = {"IONOGRAMA SERICO": "IONOGRAMA"}
_MAPA_ACENTOS = str.maketrans(
    "ÁÉÍÓÚáéíóúÜüÀÈÌÒÙàèìòù", "AEIOUaeiouUuAEIOUaeiou"
)
_PATRON_CUALITATIVO = re.compile(r"[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ .+/<>()-]{0,39}")


def normalizar_seccion_laboratorio(linea: str) -> str:
    """Devuelve el nombre canónico sin ocultar subsecciones desconocidas."""
    normalizada = linea.translate(_MAPA_ACENTOS).strip().strip("-").strip().upper()
    return _ALIAS_SECCIONES.get(normalizada, normalizada)


def es_encabezado_documento_laboratorio(linea: str) -> bool:
    return normalizar_seccion_laboratorio(linea) == "LABORATORIO DE ANALISIS CLINICOS"


def es_resultado_cualitativo_estructurado(valor: str) -> bool:
    """Acepta una celda breve en mayúsculas; rechaza prosa narrativa."""
    limpio = valor.strip()
    return bool(
        limpio
        and any(caracter.isalpha() for caracter in limpio)
        and len(limpio.split()) <= 4
        and _PATRON_CUALITATIVO.fullmatch(limpio)
    )
