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

**Nota PR9**: la lógica de redacción (regex DNI + spans del motor) que este
módulo originaba en PR8 se extrajo a `pii/redaccion.py` como módulo
compartido -- reusada acá y también por `salida/constructor_registro.py`
para cerrar el gap de redacción de texto libre en el registro de salida (ver
docstring de ese módulo). Este archivo importa de ahí en vez de definir su
propia copia del regex/las funciones.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.pii.redaccion import DetectorEntidades, MARCADOR_REDACTADO, redactar_texto

#: Defensa primaria (capa 1). Ver design.md, decisión "Sin PII en cola, logs
#: ni DLQ": "`bitacora_segura` serializa únicamente campos de una whitelist
#: (`id_documento`, `tipo_documento`, `etapa`, `codigo`, `duracion_ms`); un
#: campo no declarado se descarta, no se loguea 'por las dudas'."
CAMPOS_PERMITIDOS: frozenset[str] = frozenset(
    {"id_documento", "tipo_documento", "etapa", "codigo", "duracion_ms"}
)
CODIGOS_SEGUROS: frozenset[str] = frozenset(codigo.value for codigo in CodigoErrorDocumento)


def _redactar(valor: Any, motor_pii: DetectorEntidades | None) -> Any:
    if not isinstance(valor, str):
        return valor
    return redactar_texto(valor, motor_pii=motor_pii)


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


def contar_codigos_seguros(eventos: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Cuenta sólo códigos de dominio, sin propagar texto libre a métricas."""
    return dict(
        Counter(
            codigo
            for evento in eventos
            if isinstance((codigo := evento.get("codigo")), str) and codigo in CODIGOS_SEGUROS
        )
    )


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
