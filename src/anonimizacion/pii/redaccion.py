"""Redacción compartida de PII en texto libre (fix aditivo, cierre de gap PR7/PR8 -> PR9).

**Contexto del gap** (ver `apply-progress` de PR7/PR8 y `pipeline/ejecutor.py`,
docstring de `_resolver_documento`): `pii/politica.py::clasificar` ya
DETECTA PII en texto libre desde PR4 (`_detecciones_texto_libre`, vía
`MotorPii.detectar` sobre `ContenidoEco.secciones_texto` -- un nombre
mencionado incidentalmente en la conclusión dictada del eco). Pero hasta
PR8 nadie usaba esos hallazgos para REDACTAR el texto antes de que
`salida/constructor_registro.py` armara el `RegistroAnonimizado` final: la
detección corría, y el resultado se descartaba. Sin esto, un eco con texto
libre que mencione un nombre real llegaba sin redactar al registro de
salida, violando el requirement "Cero PII en el registro de salida" (spec
`anonymized-output`).

**Origen de este módulo**: extraído de `observabilidad/bitacora_segura.py`
(PR8, tasks.md 10.1), que ya implementaba exactamente esta lógica de
redacción (regex DNI + spans del motor de PII) como su "filtro de
redacción" (capa 2). En vez de reimplementarla o duplicarla, PR9 la mueve
acá como módulo compartido y la reusa en DOS puntos:

1. `observabilidad/bitacora_segura.py` -- ahora importa de acá en vez de
   definir el regex/las funciones de forma privada.
2. `salida/constructor_registro.py` -- aplica `redactar_texto` sobre cada
   `SeccionTextoEco.texto` antes de armar `FilaTextoSeccionEco`, con el
   mismo principio de "modo degradado" que `bitacora_segura`: si no se
   inyecta un `motor_pii` (evitar cargar spaCy si el llamador no lo tiene a
   mano), igual se aplica el regex de DNI; el composition-root real del
   pipeline (`pipeline/ejecutor.py::EjecutorPipeline._emitir`) SIEMPRE
   inyecta el `MotorPii` ya cargado que usa para el resto del pipeline, así
   que en producción la redacción por NER está activa.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol

MARCADOR_REDACTADO = "[REDACTADO]"

# Mismo patrón de forma que `pii/reconocedores/dni_ar.py::_PATRONES` (con
# puntos y sin puntos), simplificado: acá no hace falta el score ni la
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


def redactar_por_regex(texto: str) -> str:
    """Reemplaza cualquier patrón de DNI (con o sin puntos) por `MARCADOR_REDACTADO`."""
    return _PATRON_DNI.sub(MARCADOR_REDACTADO, texto)


def redactar_por_motor(texto: str, motor: DetectorEntidades) -> str:
    """Reemplaza cada span que `motor.detectar` marque como entidad por `MARCADOR_REDACTADO`."""
    detecciones = motor.detectar(texto)
    if not detecciones:
        return texto
    # reemplazar de atrás para adelante: así los offsets de las detecciones
    # anteriores (calculadas sobre el texto original) siguen siendo válidos.
    for deteccion in sorted(detecciones, key=lambda d: d.inicio, reverse=True):
        texto = texto[: deteccion.inicio] + MARCADOR_REDACTADO + texto[deteccion.fin :]
    return texto


def redactar_texto(texto: str, *, motor_pii: DetectorEntidades | None = None) -> str:
    """Aplica ambas capas sobre `texto`: regex DNI siempre, motor de PII si se inyecta.

    `motor_pii=None` es el modo degradado (solo regex, ver docstring del
    módulo) -- nunca se instancia un `MotorPii` acá adentro, porque cargarlo
    implica cargar spaCy, un costo que este módulo no debe pagar por sí
    mismo; queda a cargo de quien lo llame decidir si lo inyecta o no.
    """
    redactado = redactar_por_regex(texto)
    if motor_pii is not None:
        redactado = redactar_por_motor(redactado, motor_pii)
    return redactado
