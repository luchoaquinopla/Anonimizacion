"""Generación de claves pseudónimas HMAC-SHA256 (nunca hash simple: el DNI es enumerable y
sería reversible por fuerza bruta sin el pepper). Namespaces con prefijo propio por tipo de identidad."""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date

VERSION_CLAVE_ACTUAL = 1

_LONGITUD_CLAVE_BYTES = 16
_ESPACIOS_MULTIPLES = re.compile(r"\s+")


def canonicalizar_dni(dni: str) -> str:
    """Normaliza un DNI a su forma canónica (sin puntos/espacios/ceros a izquierda), para que
    `"12.345.678"` y `"012345678"` produzcan la misma clave."""
    limpio = dni.replace(".", "").replace(" ", "")
    sin_ceros = limpio.lstrip("0")
    return sin_ceros or "0"


def normalizar_nombre(nombre: str) -> str:
    """Normaliza un nombre para que variaciones de espaciado/mayúsculas no cambien la clave."""
    colapsado = _ESPACIOS_MULTIPLES.sub(" ", nombre.strip())
    return colapsado.casefold()


def _canonicalizar_nombre_bridge(nombre: str) -> str:
    """Canonicaliza por `apellido|primer_nombre` (apellido primero, calibrado contra la única
    muestra real) para que laboratorio y ECG del mismo paciente produzcan la misma clave puente.
    Sólo se usa en `generar_id_alt_paciente`; afloja algo la protección contra homónimos, aceptado."""
    normalizado = normalizar_nombre(nombre)
    if "," in normalizado:
        apellido_bruto, _, resto = normalizado.partition(",")
        apellido = normalizar_nombre(apellido_bruto)
        tokens_resto = normalizar_nombre(resto).split(" ") if normalizar_nombre(resto) else []
        primer_nombre = tokens_resto[0] if tokens_resto else ""
    else:
        tokens = normalizado.split(" ") if normalizado else []
        apellido = tokens[0] if tokens else ""
        primer_nombre = tokens[1] if len(tokens) > 1 else ""
    return f"{apellido}|{primer_nombre}"


def _hmac_hex(pepper: bytes, mensaje: str) -> str:
    digesto = hmac.new(pepper, mensaje.encode("utf-8"), hashlib.sha256).digest()
    return digesto[:_LONGITUD_CLAVE_BYTES].hex()


def generar_id_paciente(pepper: bytes, dni: str) -> str:
    """`id_paciente = HMAC(pepper, canonical(dni))[:16 bytes]` en hex."""
    return _hmac_hex(pepper, canonicalizar_dni(dni))


def generar_id_alt_paciente(pepper: bytes, nombre: str, fecha_nac: str) -> str:
    """`id_alt_paciente = HMAC(pepper, "alt|" + nombre_bridge + "|" + fecha_nac)`. Se usa cuando
    el documento no trae DNI (el ECG); ver `resolutor_claves.py` para el puente a `id_paciente`."""
    mensaje = f"alt|{_canonicalizar_nombre_bridge(nombre)}|{fecha_nac.strip()}"
    return _hmac_hex(pepper, mensaje)


def generar_id_medico(pepper: bytes, nombre: str) -> str:
    """`id_medico = HMAC(pepper, "medico|" + nombre_normalizado)` (decisión Q3)."""
    mensaje = f"medico|{normalizar_nombre(nombre)}"
    return _hmac_hex(pepper, mensaje)


def generar_id_matricula_medico(pepper: bytes, matricula: str) -> str:
    """`id_matricula_medico = HMAC(pepper, "matricula_medico|" + matricula)`. Identificador
    directo del médico, pseudonimizado en su propio namespace para no colisionar con `id_medico`."""
    mensaje = f"matricula_medico|{matricula.strip()}"
    return _hmac_hex(pepper, mensaje)


def generar_clave_documento(pepper: bytes, sha256: str) -> str:
    """`clave_documento = HMAC(pepper, "documento|" + sha256)[:16 bytes]` en hex. El `sha256`
    crudo -- probaría pertenencia al corpus con el PDF original -- nunca se publica."""
    mensaje = f"documento|{sha256.strip().lower()}"
    return _hmac_hex(pepper, mensaje)


def generar_id_episodio(pepper: bytes, id_paciente: str, fecha_ancla: date) -> str:
    """`id_episodio = HMAC(pepper, id_paciente + "|" + fecha_ancla)`. Función pura,
    determinística: reprocesar el mismo lote produce siempre el mismo `id_episodio`."""
    mensaje = f"{id_paciente}|{fecha_ancla.isoformat()}"
    return _hmac_hex(pepper, mensaje)
