"""Resolución de claves de identidad -- el laboratorio como puente (spec `patient-pseudonymization`).

Ver design.md, decisión "Pseudonimización con HMAC y doble clave de
identidad". Problema que resuelve este módulo: el ECG no trae DNI (solo un ID
interno de estudio), así que no puede calcular `id_paciente` directamente.
Pero el laboratorio SÍ trae nombre + DNI + fecha de nacimiento, y por lo
tanto puede calcular ambas claves de un mismo paciente y dejar registrado el
puente `id_alt_paciente -> id_paciente`.

Flujo real:

1. Llega el laboratorio de un paciente -> `resolver_claves` calcula
   `id_paciente` (vía DNI) y `id_alt_paciente` (vía nombre+fecha_nac), y
   registra el puente en `ResolutorClaves`.
2. Llega el ECG del mismo paciente (antes o después no importa) -> como no
   tiene DNI, `resolver_claves` calcula solo `id_alt_paciente` y busca el
   puente. Si el lab de ese paciente YA se procesó, lo encuentra y devuelve
   el `id_paciente` real.
3. Si el ECG llega ANTES que el lab de ese paciente (o el lab nunca llega),
   no hay puente que buscar -> no hay ninguna clave resoluble ->
   `ErrorParseo(CLAVE_PII_NO_RESUELTA)` -> el documento va a cuarentena.
   El linkage se recomputa en batch (design.md, "Migration / Rollout"), así
   que reprocesar ese mismo ECG más tarde (una vez que el lab ya se
   proceso) es idempotente y ahora sí resuelve.

`ResolutorClaves` es la tabla de resolución en memoria para esta fase (PR5).
En Fase 7 (`salida/`, ver tasks.md 7.1) se respalda con la tabla Postgres
`vinculo_paciente(id_alt_paciente, id_paciente)` (design.md, decisión Q1);
esta clase queda como la interfaz que esa fase implementa contra una tabla
real, sin cambiar el contrato de `resolver_claves`.
"""

from __future__ import annotations

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, IdentidadCruda
from anonimizacion.pseudonimizacion.claves import (
    VERSION_CLAVE_ACTUAL,
    generar_id_alt_paciente,
    generar_id_paciente,
)


class ResolutorClaves:
    """Tabla de resolución `id_alt_paciente -> id_paciente` (puente vía laboratorio).

    Implementación en memoria para PR5; el contrato (`registrar_puente` /
    `resolver`) es el que Fase 7 respalda con la tabla Postgres
    `vinculo_paciente`.
    """

    def __init__(self) -> None:
        self._puentes: dict[str, str] = {}

    def registrar_puente(self, id_alt_paciente: str, id_paciente: str) -> None:
        self._puentes[id_alt_paciente] = id_paciente

    def resolver(self, id_alt_paciente: str) -> str | None:
        return self._puentes.get(id_alt_paciente)


def resolver_claves(
    identidad: IdentidadCruda,
    pepper: bytes,
    resolutor: ResolutorClaves,
    *,
    id_documento: str,
    etapa: str,
) -> ClavesPaciente:
    """Resuelve `ClavesPaciente` para un documento; lanza `CLAVE_PII_NO_RESUELTA` si no se puede.

    `id_documento` no se usa en el cálculo -- se recibe para que quien
    capture `ErrorParseo` pueda enriquecer el `ErrorDocumento` resultante
    con el id sin que este módulo tenga que conocer esa estructura.
    """
    del id_documento  # ver docstring: reservado para quien capture la excepción

    dni = identidad.dni.get_secret_value() if identidad.dni is not None else None
    nombre = identidad.nombre.get_secret_value()
    fecha_nac = identidad.fecha_nac.get_secret_value() if identidad.fecha_nac is not None else None

    if dni is not None:
        id_paciente = generar_id_paciente(pepper, dni)
        id_alt_paciente: str | None = None
        if fecha_nac is not None:
            id_alt_paciente = generar_id_alt_paciente(pepper, nombre, fecha_nac)
            resolutor.registrar_puente(id_alt_paciente, id_paciente)  # el lab actúa de puente
        return ClavesPaciente(
            id_paciente=id_paciente,
            id_alt_paciente=id_alt_paciente,
            version_clave=VERSION_CLAVE_ACTUAL,
        )

    if fecha_nac is not None:
        id_alt_paciente = generar_id_alt_paciente(pepper, nombre, fecha_nac)
        id_paciente_resuelto = resolutor.resolver(id_alt_paciente)
        if id_paciente_resuelto is not None:
            return ClavesPaciente(
                id_paciente=id_paciente_resuelto,
                id_alt_paciente=id_alt_paciente,
                version_clave=VERSION_CLAVE_ACTUAL,
            )

    raise ErrorParseo(CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA, etapa=etapa)
