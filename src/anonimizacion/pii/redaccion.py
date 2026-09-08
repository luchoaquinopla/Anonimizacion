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

**Tercera capa: comparación exacta contra nombres ya conocidos (Tarea 2,
hallazgo de auditoría)**. `pii/politica.py` (docstring del módulo, líneas
24-26) documentaba desde PR4 que decidir a qué persona pertenece un
hallazgo de texto libre "es una decisión de Fase 6/7 que puede requerir
contexto adicional (p.ej. comparar contra el nombre ya conocido del
paciente/médico de ese mismo documento)" -- pero rastreando el código real
de Fase 6/7 (este módulo y `salida/constructor_registro.py`) esa
comparación NUNCA se implementó: `redactar_texto` solo corría regex de DNI
+ NER, nunca comparaba contra `documento.identidad.nombre` ni contra el
nombre del médico de ese mismo documento. Era una intención escrita en un
comentario, no código -- exactamente el patrón de "afirmación falsa en
comentario/docstring" que este repo ya viene arrastrando (ver AGENTS.md).

`redactar_por_nombres_conocidos` cierra ese hueco: el nombre del paciente y
el del médico de un documento son datos YA CONOCIDOS con certeza (vienen
del header parseado, no de una inferencia probabilística), así que
cualquier aparición literal de esos nombres -o de sus componentes
individuales, por si el texto libre menciona solo el apellido o solo el
nombre de pila- se redacta por comparación EXACTA, determinística,
independiente de que el NER los reconozca o no como entidad. Es la red de
contención más fuerte posible para el escenario de fuga más probable: que
la conclusión dictada mencione al propio paciente o al médico firmante de
ESE MISMO documento (no un gazetteer genérico, que solo cubriría apellidos
que alguien haya pensado en poner en una lista).
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
_PATRON_DNI = re.compile(
    r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}(?!\d)|(?<![\d.])\d{3}\.\d{3}(?!\d)|(?<!\d)\d{6,8}(?!\d)"
)

# Tokens de un nombre por debajo de esta longitud (conectores como "de",
# "la", "y", "del") no se usan solos como gatillo de redacción: son palabras
# comunes del idioma, redactarlas sueltas produciría ruido masivo sin
# proteger nada (ver `_componentes_nombre`).
_TOKEN_MINIMO = 3


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


def _componentes_nombre(nombre: str) -> tuple[str, ...]:
    """Nombre completo + cada uno de sus tokens de longitud significativa.

    Un hallazgo de texto libre puede mencionar el nombre completo tal cual
    figura en el header ("Roberto Fernandez"), o solo el apellido ("Dr.
    Fernandez"), o solo el nombre de pila -- cualquiera de las tres formas
    debe redactarse. Los tokens por debajo de `_TOKEN_MINIMO` (conectores
    como "de"/"la"/"y") se excluyen: ver docstring de esa constante.
    """
    tokens = nombre.split()
    return tuple([nombre] + [token for token in tokens if len(token) >= _TOKEN_MINIMO])


def redactar_por_nombres_conocidos(texto: str, nombres: Sequence[str]) -> str:
    """Redacta coincidencias EXACTAS del nombre completo o sus componentes.

    A diferencia de `redactar_por_motor` (que depende de que spaCy reconozca
    la entidad), esta función no infiere nada: `nombres` son identidades YA
    CONOCIDAS con certeza para ESTE documento (el paciente y/o el médico,
    leídos del header parseado por el llamador -- ver
    `salida/constructor_registro.py`). Cualquier aparición literal, sin
    importar mayúsculas/minúsculas, se reemplaza por `MARCADOR_REDACTADO`.

    Los componentes más largos se intentan primero (`sorted(..., reverse=True)`)
    para que "Roberto Fernandez" se redacte como una sola unidad en vez de
    dejar dos reemplazos separados de "Roberto" y "Fernandez" cuando el
    nombre completo aparece junto.
    """
    if not texto or not nombres:
        return texto
    componentes: set[str] = set()
    for nombre in nombres:
        if nombre:
            componentes.update(_componentes_nombre(nombre))
    if not componentes:
        return texto
    patron = re.compile(
        "|".join(rf"\b{re.escape(c)}\b" for c in sorted(componentes, key=len, reverse=True)),
        re.IGNORECASE,
    )
    return patron.sub(MARCADOR_REDACTADO, texto)


def redactar_texto(
    texto: str,
    *,
    motor_pii: DetectorEntidades | None = None,
    nombres_conocidos: Sequence[str] | None = None,
) -> str:
    """Aplica las capas de redacción sobre `texto`, en orden de certeza decreciente:

    1. Regex de DNI (siempre).
    2. Comparación exacta contra `nombres_conocidos`, si se pasan (Tarea 2:
       nombre del paciente/médico de ESTE documento -- certeza, no inferencia).
    3. `motor_pii` (NER), si se inyecta -- el único paso probabilístico.

    `motor_pii=None` es el modo degradado (ver docstring del módulo) -- nunca
    se instancia un `MotorPii` acá adentro, porque cargarlo implica cargar
    spaCy, un costo que este módulo no debe pagar por sí mismo; queda a
    cargo de quien lo llame decidir si lo inyecta o no. `nombres_conocidos`
    no tiene ese costo (es comparación de string), así que se aplica siempre
    que se pasen, con o sin `motor_pii`.
    """
    redactado = redactar_por_regex(texto)
    if nombres_conocidos:
        redactado = redactar_por_nombres_conocidos(redactado, nombres_conocidos)
    if motor_pii is not None:
        redactado = redactar_por_motor(redactado, motor_pii)
    return redactado
