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
- `clave_documento` (prefijo `"documento|"`): HMAC del `sha256` del contenido
  del artefacto -- identidad estable del documento (spec
  `escritura-idempotente`). El `sha256` crudo nunca sale de este módulo hacia
  ningún destino de salida.

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


def _canonicalizar_nombre_bridge(nombre: str) -> str:
    """Canonicaliza un nombre por `apellido|primer_nombre` para el puente lab<->ECG.

    Fix post-merge (encontrado corriendo el pipeline contra PDFs reales): el
    mismo paciente aparece escrito distinto según el tipo de documento del
    mismo instituto -- p.ej. laboratorio `"Apellido , Nombre SegundoNombre"`
    (apellido, coma, nombre(s) de pila completos) vs ECG `"Apellido Nombre"`
    (apellido nombre, sin coma, sin segundo nombre). `normalizar_nombre` por sí
    sola (que solo colapsa espacios y hace casefold) no alcanza para que esos
    dos strings produzcan la misma clave, así que el puente
    (`resolutor_claves.py`) nunca encontraba el match y el ECG quedaba en
    cuarentena aunque el laboratorio del mismo paciente ya se había procesado.

    Se usa SOLO acá, dentro de `generar_id_alt_paciente` -- NO en
    `generar_id_medico` ni en ningún otro lugar. El alcance de este fix es
    específicamente el puente de identidad del paciente.

    Trade-off ACEPTADO explícitamente con el usuario: usar solo
    apellido+primer_nombre (en vez del nombre completo) afloja un poco la
    protección contra homónimos que ya existía en
    `resolutor_claves.py::ResolutorClaves` -- dos personas DISTINTAS con el
    mismo apellido, el mismo primer nombre y la MISMA fecha de nacimiento
    exacta ahora colisionan más fácil que antes (antes el segundo nombre
    completo las distinguía). Se acepta ese costo porque sigue siendo mucho
    más específico que usar solo la fecha de nacimiento, y porque resuelve un
    caso real confirmado del mismo instituto.

    Formato asumido -- CALIBRADO CONTRA LA ÚNICA MUESTRA REAL DISPONIBLE, igual
    advertencia que otros fixes de recalibración en este módulo: el apellido va
    PRIMERO en ambos formatos.
    - Con coma (`"Apellido , Nombre(s)"`): apellido = todo lo que está ANTES de
      la coma; primer_nombre = el PRIMER token después de la coma.
    - Sin coma (`"Apellido Nombre(s)"`): primer token = apellido; segundo token
      = primer_nombre.
    Podría no generalizar a layouts con el orden invertido (nombre antes que
    apellido) -- no confirmado contra ninguna muestra real con ese orden.
    """
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
    """`id_alt_paciente = HMAC(pepper, "alt|" + nombre_canonicalizado_bridge + "|" + fecha_nac)`.

    Se usa cuando el documento no trae DNI (el ECG); ver `resolutor_claves.py`
    para el mecanismo de puente que lo resuelve a `id_paciente`.

    El nombre se canonicaliza vía `_canonicalizar_nombre_bridge` (apellido +
    primer nombre de pila, NO el nombre completo) -- ver su docstring para el
    fix post-merge que motivó este cambio y el trade-off aceptado con el
    usuario. Este tratamiento especial es exclusivo de esta función; NO se usa
    en `generar_id_medico` ni en ningún otro namespace de este módulo.
    """
    mensaje = f"alt|{_canonicalizar_nombre_bridge(nombre)}|{fecha_nac.strip()}"
    return _hmac_hex(pepper, mensaje)


def generar_id_medico(pepper: bytes, nombre: str) -> str:
    """`id_medico = HMAC(pepper, "medico|" + nombre_normalizado)` (decisión Q3)."""
    mensaje = f"medico|{normalizar_nombre(nombre)}"
    return _hmac_hex(pepper, mensaje)


def generar_id_matricula_medico(pepper: bytes, matricula: str) -> str:
    """`id_matricula_medico = HMAC(pepper, "matricula_medico|" + matricula)` (decisión Q3, Fase 7).

    Q3 dice explícitamente que la matrícula "recibe el mismo tratamiento"
    que el nombre del médico -- es un identificador directo, así que se
    pseudonimiza igual que `id_medico`, pero en su propio namespace (prefijo
    distinto) para que nunca colisione con `id_medico` ni con ningún otro.
    Usada por `salida/constructor_registro.py` (Fase 7) al construir
    `ContenidoEcoSalida.id_matricula_informante` a partir de
    `FirmaMedico.matricula`.
    """
    mensaje = f"matricula_medico|{matricula.strip()}"
    return _hmac_hex(pepper, mensaje)


def generar_clave_documento(pepper: bytes, sha256: str) -> str:
    """`clave_documento = HMAC(pepper, "documento|" + sha256_normalizado)[:16 bytes]` en hex.

    Identidad estable del documento (spec `escritura-idempotente`): el mismo
    contenido produce siempre la misma clave, y el `sha256` crudo -- que sí
    permitiría a cualquiera con el PDF original probar pertenencia al
    corpus -- nunca se publica en ningún destino.
    """
    mensaje = f"documento|{sha256.strip().lower()}"
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
