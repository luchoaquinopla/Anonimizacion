"""Bitácora segura de trazabilidad: dos capas de defensa, whitelist primero. La
whitelist de campos (`CAMPOS_PERMITIDOS`) es la barrera que importa -- allowlist, no
depende de reconocer el dato peligroso. El filtro de redacción (regex DNI + spans del
motor de PII) es respaldo, nunca la única defensa: una lista negra falla en silencio
justo con el dato que no previste. `motor_pii` se inyecta; sin él, el filtro opera en
modo degradado (sólo regex DNI)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from anonimizacion.pii.redaccion import DetectorEntidades, redactar_texto

#: Defensa primaria (capa 1): un campo no declarado se descarta, nunca se loguea.
CAMPOS_PERMITIDOS: frozenset[str] = frozenset(
    {"id_documento", "tipo_documento", "etapa", "codigo", "duracion_ms"}
)


def _redactar(valor: Any, motor_pii: DetectorEntidades | None) -> Any:
    if not isinstance(valor, str):
        return valor
    return redactar_texto(valor, motor_pii=motor_pii)


def filtrar_y_redactar(
    evento: Mapping[str, Any], *, motor_pii: DetectorEntidades | None = None
) -> dict[str, Any]:
    """Aplica las dos capas de defensa y devuelve el dict listo para loguear:
    whitelist de claves, luego redacción de DNIs/entidades sobre los valores que sobreviven."""
    return {
        clave: _redactar(valor, motor_pii)
        for clave, valor in evento.items()
        if clave in CAMPOS_PERMITIDOS
    }


class BitacoraSegura:
    """Logger de trazabilidad que, por construcción, no puede emitir PII. Envuelve un
    `logging.Logger` estándar; sólo garantiza que lo que llega ya pasó por `filtrar_y_redactar`."""

    def __init__(
        self,
        logger: logging.Logger | None = None,
        *,
        motor_pii: DetectorEntidades | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger("anonimizacion.bitacora")
        self._motor_pii = motor_pii

    def registrar(
        self, evento: Mapping[str, Any], *, nivel: int = logging.INFO
    ) -> dict[str, Any]:
        """Filtra+redacta `evento` y lo loguea; devuelve el dict efectivamente logueado."""
        seguro = filtrar_y_redactar(evento, motor_pii=self._motor_pii)
        self._logger.log(nivel, "%s", seguro)
        return seguro
