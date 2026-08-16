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

    Homónimos y ambigüedad (fix post-PR5): `id_alt_paciente` se deriva SOLO
    de nombre+fecha_nac (ver `claves.py`), no es un identificador único de
    persona real. Dos pacientes reales distintos con el mismo nombre y la
    misma fecha de nacimiento producen el MISMO `id_alt_paciente`. Si eso
    pasa, `registrar_puente` NO sobrescribe en silencio: marca ese
    `id_alt_paciente` como ambiguo, y un `id_alt_paciente` ambiguo nunca
    vuelve a resolver (`resolver` devuelve `None` permanentemente para él,
    incluso si un registro posterior "desempataría" -- no hay forma
    automática segura de saber cuál `id_paciente` es el correcto sin
    intervención humana). Registrar el mismo `id_alt_paciente` con el MISMO
    `id_paciente` más de una vez (reprocesar el mismo laboratorio) es
    idempotente y NO dispara ambigüedad.

    Nota de diseño para Fase 7 (tabla Postgres `vinculo_paciente`, ver
    design.md decisión Q1, tasks.md 7.1): la implementación que respalde
    esta clase con una tabla real TIENE que preservar esta misma semántica
    al persistir el puente -- por ejemplo, guardando múltiples filas
    candidatas por `id_alt_paciente` con un flag `ambiguo` (o tabla de
    conflictos separada), o una restricción/trigger que detecte en el
    INSERT que ya existe una fila con el mismo `id_alt_paciente` pero
    distinto `id_paciente` y marque ambigüedad en vez de pisar la fila
    existente. Un simple `UPSERT ... ON CONFLICT (id_alt_paciente) DO
    UPDATE` reintroduciría exactamente este bug (pisaría el puente
    anterior en silencio) -- quien implemente PR6 no debe usar ese patrón
    para esta tabla sin resolver primero la detección de conflicto.
    """

    def __init__(self) -> None:
        self._puentes: dict[str, str] = {}
        self._ambiguos: set[str] = set()

    def registrar_puente(self, id_alt_paciente: str, id_paciente: str) -> None:
        if id_alt_paciente in self._ambiguos:
            return  # ya ambiguo -- permanece ambiguo, no hay vuelta atrás

        existente = self._puentes.get(id_alt_paciente)
        if existente is None:
            self._puentes[id_alt_paciente] = id_paciente
        elif existente != id_paciente:
            # mismo id_alt_paciente, id_paciente distinto -> homónimos reales:
            # no hay forma segura de saber cuál es el correcto, se marca ambiguo
            # y se descarta cualquier candidato previo.
            del self._puentes[id_alt_paciente]
            self._ambiguos.add(id_alt_paciente)
        # si existente == id_paciente: reprocesamiento idempotente, no-op

    def resolver(self, id_alt_paciente: str) -> str | None:
        if id_alt_paciente in self._ambiguos:
            return None
        return self._puentes.get(id_alt_paciente)

    def es_ambiguo(self, id_alt_paciente: str) -> bool:
        return id_alt_paciente in self._ambiguos


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
        if resolutor.es_ambiguo(id_alt_paciente):
            # hay candidatos, pero son conflictivos (homónimos) -- reprocesar
            # no lo arregla solo, a diferencia de CLAVE_PII_NO_RESUELTA.
            raise ErrorParseo(CodigoErrorDocumento.CLAVE_PII_AMBIGUA, etapa=etapa)

    raise ErrorParseo(CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA, etapa=etapa)
