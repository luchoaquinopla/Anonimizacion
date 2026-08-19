"""Whitelist de IDs no sensibles permitidos para trazabilidad."""

from __future__ import annotations

import re

_IDENTIFICADOR_SEGURO = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")

REFERENCIAS_PERMITIDAS: dict[str, frozenset[str]] = {
    "ecg.nombre": frozenset({"ecg.nombre"}),
    "ecg.id_estudio": frozenset({"ecg.id_estudio"}),
    "ecg.fecha_estudio": frozenset({"ecg.fecha_estudio"}),
    "ecg.fecha_nacimiento": frozenset({"ecg.fecha_nacimiento"}),
    "ecg.vent_rate": frozenset({"ecg.vent_rate"}),
    "ecg.pr_interval": frozenset({"ecg.pr_interval"}),
    "ecg.qrs_duration": frozenset({"ecg.qrs_duration"}),
    "ecg.qt_qtc": frozenset({"ecg.qt_qtc"}),
    "ecg.ejes": frozenset({"ecg.ejes"}),
    "laboratorio.nombre": frozenset({"laboratorio.nombre"}),
    "laboratorio.dni": frozenset({"laboratorio.dni"}),
    "laboratorio.fecha_estudio": frozenset({"laboratorio.fecha_estudio"}),
    "laboratorio.resultado": frozenset({"laboratorio.resultado"}),
    "eco.nombre": frozenset({"eco.nombre"}),
    "eco.dni": frozenset({"eco.dni"}),
    "eco.fecha_estudio": frozenset({"eco.fecha_estudio"}),
    "eco.numero_estudio": frozenset({"eco.numero_estudio"}),
    "eco.medida": frozenset({"eco.medida"}),
    "eco.seccion": frozenset({"eco.seccion"}),
    "eco.firma": frozenset({"eco.firma"}),
}


def validar_campo_reconciliacion(campo: str) -> None:
    """Acepta solo IDs declarados, nunca contenido de un documento."""
    if not _IDENTIFICADOR_SEGURO.fullmatch(campo) or campo not in REFERENCIAS_PERMITIDAS:
        raise ValueError("campo inválido")
