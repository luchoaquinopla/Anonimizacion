"""Generación de claves pseudónimas HMAC (spec `patient-pseudonymization`).

Ver design.md, decisión "Pseudonimización con HMAC y doble clave de
identidad": se usa `hmac.new(pepper, mensaje, hashlib.sha256)` -- HMAC con
clave secreta (el pepper), NO un hash simple. Un hash simple (p.ej.
`sha256(dni)`) es reversible por fuerza bruta porque el espacio de DNIs es
enumerable (unos pocos millones de valores); HMAC con una clave secreta que
nunca sale del worker hace que ese ataque sea inviable sin el pepper.

Namespaces (mensajes con prefijo propio, para que nunca puedan colisionar
entre sí aunque compartan pepper):

- `id_paciente`: HMAC del DNI canonicalizado -- la clave "real" del paciente.
- `id_alt_paciente` (prefijo `"alt|"`): HMAC de nombre+fecha de nacimiento --
  clave alternativa para documentos que no traen DNI (el ECG). Ver
  `resolutor_claves.py` para cómo se resuelve a `id_paciente` vía el
  laboratorio.
- `id_medico` (prefijo `"medico|"`): namespace propio del profesional (Q3),
  nunca mezclado con la identidad del paciente.
- `id_episodio` (prefijo implícito por concatenación `id_paciente + "|" +
  fecha_ancla`): ver `vinculacion.py`.

Todas las claves se truncan a 16 bytes (128 bits) del digest HMAC-SHA256 y se
codifican en hex -- suficiente espacio para evitar colisiones a la escala de
este dataset, y más corto que el hex de 32 bytes para las columnas de linkage.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date

VERSION_CLAVE_ACTUAL = 1

_LONGITUD_CLAVE_BYTES = 16
_ESPACIOS_MULTIPLES = re.compile(r"\s+")


def canonicalizar_dni(dni: str) -> str:
    """Normaliza un DNI a su forma canónica: sin puntos/espacios, sin ceros a izquierda.

    `"12.345.678"`, `"12 345 678"` y `"012345678"` deben producir la misma
    clave -- son el mismo DNI escrito de formas distintas por cada parser.
    """
    limpio = dni.replace(".", "").replace(" ", "")
    sin_ceros = limpio.lstrip("0")
    return sin_ceros or "0"


def normalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre para que variaciones de espaciado/mayúsculas no cambien la clave."""
    colapsado = _ESPACIOS_MULTIPLES.sub(" ", nombre.strip())
    return colapsado.casefold()


def _hmac_hex(pepper: bytes, mensaje: str) -> str:
    digesto = hmac.new(pepper, mensaje.encode("utf-8"), hashlib.sha256).digest()
    return digesto[:_LONGITUD_CLAVE_BYTES].hex()


def generar_id_paciente(pepper: bytes, dni: str) -> str:
    """`id_paciente = HMAC(pepper, canonical(dni))[:16 bytes]` en hex."""
    return _hmac_hex(pepper, canonicalizar_dni(dni))


def generar_id_alt_paciente(pepper: bytes, nombre: str, fecha_nac: str) -> str:
    """`id_alt_paciente = HMAC(pepper, "alt|" + nombre_normalizado + "|" + fecha_nac)`.

    Se usa cuando el documento no trae DNI (el ECG); ver `resolutor_claves.py`
    para el mecanismo de puente que lo resuelve a `id_paciente`.
    """
    mensaje = f"alt|{normalizar_nombre(nombre)}|{fecha_nac.strip()}"
    return _hmac_hex(pepper, mensaje)


def generar_id_medico(pepper: bytes, nombre: str) -> str:
    """`id_medico = HMAC(pepper, "medico|" + nombre_normalizado)` (decisión Q3)."""
    mensaje = f"medico|{normalizar_nombre(nombre)}"
    return _hmac_hex(pepper, mensaje)


def generar_id_episodio(pepper: bytes, id_paciente: str, fecha_ancla: date) -> str:
    """`id_episodio = HMAC(pepper, id_paciente + "|" + fecha_ancla)`.

    Determinístico y recomputable: no es una mutación incremental de estado,
    sino una función pura de `(id_paciente, fecha_ancla)` -- reprocesar el
    mismo lote en batch produce siempre el mismo `id_episodio` (ver
    `vinculacion.py`).
    """
    mensaje = f"{id_paciente}|{fecha_ancla.isoformat()}"
    return _hmac_hex(pepper, mensaje)
