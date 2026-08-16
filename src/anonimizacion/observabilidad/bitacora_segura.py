"""Bitácora segura de trazabilidad (tasks.md 10.1, spec `batch-processing`).

Ver design.md, decisión "Sin PII en cola, logs ni DLQ" (R4): este módulo es la
barrera (2) y (3) de las cuatro descriptas ahí. Consume dicts como los que
produce `pipeline/resultado.py::resumen_trazable()` -- u otros eventos ad hoc
del pipeline/workers -- y aplica DOS capas de defensa, en este orden de
importancia:

1. **Whitelist de campos** (defensa primaria): solo se serializa un conjunto
   FIJO y explícito de claves (`CAMPOS_PERMITIDOS`). Un campo no declarado se
   descarta directamente, nunca se loguea "por las dudas". Esta es la defensa
   que realmente importa: es una lista BLANCA (allowlist), no depende de
   reconocer el dato peligroso para excluirlo.
2. **Filtro de redacción** (defensa SEGUNDA, no la única): sobre cualquier
   string que efectivamente llegue al logger -incluso un campo de la
   whitelist, por si terminara conteniendo texto libre con PII incrustada
   por error- se reemplazan (a) patrones de DNI vía regex y (b) cualquier
   span que el motor de PII (Presidio+spaCy, `pii/motor.py::MotorPii`)
   detecte como entidad. design.md rechaza explícitamente confiar SOLO en
   este filtro: "es una lista negra, y una lista negra falla en silencio
   justo con el dato que no previste" -- por eso la whitelist es la barrera
   primaria y este filtro es un respaldo adicional.

`motor_pii` se inyecta (no se instancia acá): construir un `MotorPii` carga
spaCy, un costo que no tiene sentido pagar por cada llamada de log. El
composition-root de producción debería compartir UNA instancia de `MotorPii`
entre el pipeline de detección de PII y esta bitácora. Si no se inyecta
ninguno, el filtro sigue operando en modo reducido (solo regex DNI) -- se
documenta explícitamente como modo degradado, no como el caso esperado en
producción.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

MARCADOR_REDACTADO = "[REDACTADO]"

#: Defensa primaria (capa 1). Ver design.md, decisión "Sin PII en cola, logs
#: ni DLQ": "`bitacora_segura` serializa únicamente campos de una whitelist
#: (`id_documento`, `tipo_documento`, `etapa`, `codigo`, `duracion_ms`); un
#: campo no declarado se descarta, no se loguea 'por las dudas'."
CAMPOS_PERMITIDOS: frozenset[str] = frozenset(
    {"id_documento", "tipo_documento", "etapa", "codigo", "duracion_ms"}
)

# Mismo patrón de forma que `pii/reconocedores/dni_ar.py::_PATRONES` (con
# puntos y sin puntos), pero simplificado: acá no hace falta el score ni la
# validación de rango de Presidio -- es una segunda barrera de regex lisa y
# llana, independiente de que el motor de PII esté disponible o no.
_PATRON_DNI = re.compile(r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}(?!\d)|(?<!\d)\d{7,8}(?!\d)")


class DetectorEntidades(Protocol):
    """Lo mínimo que este módulo necesita del motor de PII.

    `MotorPii.detectar` (`pii/motor.py`) ya cumple este contrato; se declara
    acá como Protocol -no se importa `MotorPii` directamente- para poder
    inyectar dobles de test livianos sin pagar el costo de cargar spaCy.
    """

    def detectar(self, texto: str) -> Sequence[Any]: ...


def _redactar_por_regex(texto: str) -> str:
    return _PATRON_DNI.sub(MARCADOR_REDACTADO, texto)


def _redactar_por_motor(texto: str, motor: DetectorEntidades) -> str:
    detecciones = motor.detectar(texto)
    if not detecciones:
        return texto
    # reemplazar de atrás para adelante: así los offsets de las detecciones
    # anteriores (calculadas sobre el texto original) siguen siendo válidos.
    for deteccion in sorted(detecciones, key=lambda d: d.inicio, reverse=True):
        texto = texto[: deteccion.inicio] + MARCADOR_REDACTADO + texto[deteccion.fin :]
    return texto


def _redactar(valor: Any, motor_pii: DetectorEntidades | None) -> Any:
    if not isinstance(valor, str):
        return valor
    redactado = _redactar_por_regex(valor)
    if motor_pii is not None:
        redactado = _redactar_por_motor(redactado, motor_pii)
    return redactado


def filtrar_y_redactar(
    evento: Mapping[str, Any], *, motor_pii: DetectorEntidades | None = None
) -> dict[str, Any]:
    """Aplica las dos capas de defensa y devuelve el dict listo para loguear.

    Capa 1 (whitelist): descarta cualquier clave fuera de `CAMPOS_PERMITIDOS`.
    Capa 2 (redacción): sobre los valores string que sobreviven a la capa 1,
    reemplaza DNIs (regex) y, si se inyectó `motor_pii`, cualquier entidad
    que el motor detecte.
    """
    return {
        clave: _redactar(valor, motor_pii)
        for clave, valor in evento.items()
        if clave in CAMPOS_PERMITIDOS
    }


class BitacoraSegura:
    """Logger de trazabilidad que, por construcción, no puede emitir PII.

    Envuelve un `logging.Logger` estándar: no reinventa infraestructura de
    logging, solo garantiza que lo que le llega a ese logger ya pasó por
    `filtrar_y_redactar`.
    """

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
