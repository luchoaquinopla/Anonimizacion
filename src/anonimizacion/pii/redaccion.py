"""Redacción compartida de PII en texto libre, en tres capas por certeza creciente: regex DNI,
comparación exacta contra nombres ya conocidos (paciente/médico de ESE documento), NER."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol

MARCADOR_REDACTADO = "[REDACTADO]"

# Segunda barrera de regex lisa (sin score/rango de Presidio), independiente del motor de PII.
_PATRON_DNI = re.compile(
    r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}(?!\d)|(?<![\d.])\d{3}\.\d{3}(?!\d)|(?<!\d)\d{6,8}(?!\d)"
)

# Conectores ("de", "la", "y") por debajo de este largo no gatillan redacción solos: ruido masivo sin proteger nada.
_TOKEN_MINIMO = 3

# re.IGNORECASE no cubre diacríticos ("Maria" != "María"); se matchea por clase de letra base en vez de normalizar el texto (evitaría remapear offsets de redacción).
_EQUIVALENTES_ACENTUADAS: dict[str, str] = {
    "a": "aáàäâ",
    "e": "eéèëê",
    "i": "iíìïî",
    "o": "oóòöô",
    "u": "uúùüû",
    "n": "nñ",
    "c": "cç",
}

# Reverso de _EQUIVALENTES_ACENTUADAS: resuelve también cuando el nombre conocido ya trae la letra acentuada (p.ej. "í" en "María").
_BASE_POR_VARIANTE: dict[str, str] = {
    variante: base for base, variantes in _EQUIVALENTES_ACENTUADAS.items() for variante in variantes
}


class DetectorEntidades(Protocol):
    """Lo mínimo que este módulo necesita del motor de PII, sin importar `MotorPii`
    directamente: permite inyectar dobles de test livianos sin cargar spaCy."""

    def detectar(self, texto: str) -> Sequence[Any]: ...


def redactar_por_regex(texto: str) -> str:
    """Reemplaza cualquier patrón de DNI (con o sin puntos) por `MARCADOR_REDACTADO`."""
    return _PATRON_DNI.sub(MARCADOR_REDACTADO, texto)


def redactar_por_motor(texto: str, motor: DetectorEntidades) -> str:
    """Reemplaza cada span que `motor.detectar` marque como entidad por `MARCADOR_REDACTADO`."""
    detecciones = motor.detectar(texto)
    if not detecciones:
        return texto
    # De atrás para adelante: así los offsets de detecciones previas siguen siendo válidos.
    for deteccion in sorted(detecciones, key=lambda d: d.inicio, reverse=True):
        texto = texto[: deteccion.inicio] + MARCADOR_REDACTADO + texto[deteccion.fin :]
    return texto


def _componentes_nombre(nombre: str) -> tuple[str, ...]:
    """Nombre completo + cada token significativo (apellido o nombre de pila solos también
    redactan). El piso mínimo evita que una captura de header degenerada redacte todo el texto."""
    componentes = [nombre] + nombre.split()
    return tuple(c for c in componentes if len(c) >= _TOKEN_MINIMO)


def _fragmento_tolerante_a_acentos(componente: str) -> str:
    """Arma el fragmento de regex de `componente` matcheando ambas direcciones de acento
    (con/sin tilde); caracteres sin variante quedan `re.escape`d, sin volverse metacaracteres."""
    partes = []
    for caracter in componente:
        base = _BASE_POR_VARIANTE.get(caracter.lower())
        if base:
            partes.append(f"[{_EQUIVALENTES_ACENTUADAS[base]}]")
        else:
            partes.append(re.escape(caracter))
    return "".join(partes)


def redactar_por_nombres_conocidos(texto: str, nombres: Sequence[str]) -> str:
    """Redacta coincidencias EXACTAS de `nombres` (identidades ya conocidas con certeza para
    este documento), sin inferir. Componentes más largos primero, para redactar como unidad."""
    if not texto or not nombres:
        return texto
    componentes: set[str] = set()
    for nombre in nombres:
        if nombre:
            componentes.update(_componentes_nombre(nombre))
    if not componentes:
        return texto
    patron = re.compile(
        "|".join(
            rf"\b{_fragmento_tolerante_a_acentos(c)}\b"
            for c in sorted(componentes, key=len, reverse=True)
        ),
        re.IGNORECASE,
    )
    return patron.sub(MARCADOR_REDACTADO, texto)


def redactar_texto(
    texto: str,
    *,
    motor_pii: DetectorEntidades | None = None,
    nombres_conocidos: Sequence[str] | None = None,
) -> str:
    """Aplica las tres capas en orden de certeza decreciente: regex DNI, nombres conocidos,
    NER. `motor_pii=None` es modo degradado -- nunca se instancia acá, para no cargar spaCy."""
    redactado = redactar_por_regex(texto)
    if nombres_conocidos:
        redactado = redactar_por_nombres_conocidos(redactado, nombres_conocidos)
    if motor_pii is not None:
        redactado = redactar_por_motor(redactado, motor_pii)
    return redactado
