"""Resolución de claves de identidad -- el laboratorio como puente. El ECG no trae DNI, así que
`resolver_claves` calcula sólo `id_alt_paciente` (nombre+fecha_nac) y busca el puente que el
laboratorio del mismo paciente ya registró; sin puente, `CLAVE_PII_NO_RESUELTA` a cuarentena
(recomputable en batch reprocesando).

Fix: `ResolutorClavesPostgres` (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
persistencia del puente id_alt_paciente en Postgres entre corridas") cierra el gap de que nada
en el flujo real usaba el respaldo Postgres del puente -- delega a `EscritorPostgres` inyectado,
mismo contrato que `ResolutorClaves` (en memoria), sin caché propia.
"""

from __future__ import annotations

from typing import Protocol

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente, IdentidadCruda
from anonimizacion.pseudonimizacion.claves import (
    VERSION_CLAVE_ACTUAL,
    generar_id_alt_paciente,
    generar_id_paciente,
)


class ResolutorClavesProtocol(Protocol):
    """Contrato duck-typed del puente `id_alt_paciente -> id_paciente`; implementado por
    `ResolutorClaves` (memoria) y `ResolutorClavesPostgres` (persistente), misma firma."""

    def registrar_puente(self, id_alt_paciente: str, id_paciente: str) -> None: ...

    def resolver(self, id_alt_paciente: str) -> str | None: ...

    def es_ambiguo(self, id_alt_paciente: str) -> bool: ...


class ResolutorClaves:
    """Tabla de resolución `id_alt_paciente -> id_paciente` en memoria. Homónimos reales (mismo
    nombre+fecha_nac, `id_paciente` distinto) marcan el puente como ambiguo permanentemente --
    `resolver` nunca vuelve a devolverlo, sin intervención humana; reprocesar el mismo par es
    idempotente. `EscritorPostgres.registrar_vinculo` MUST preservar esta semántica: un
    `UPSERT ... ON CONFLICT DO UPDATE` simple pisaría el puente anterior en silencio."""

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


class ResolutorClavesPostgres:
    """Puente `id_alt_paciente -> id_paciente` persistente (ver docstring del módulo): delega a
    un `EscritorPostgres` inyectado, sin caché propia. No se tipa contra `EscritorPostgres`
    directamente para evitar el import cruzado desde `pseudonimizacion` hacia `salida`."""

    def __init__(self, escritor: _EscritorVinculoProtocol) -> None:
        self._escritor = escritor

    def registrar_puente(self, id_alt_paciente: str, id_paciente: str) -> None:
        self._escritor.registrar_vinculo(id_alt_paciente, id_paciente)

    def resolver(self, id_alt_paciente: str) -> str | None:
        return self._escritor.resolver_vinculo(id_alt_paciente)

    def es_ambiguo(self, id_alt_paciente: str) -> bool:
        return self._escritor.es_ambiguo(id_alt_paciente)


class _EscritorVinculoProtocol(Protocol):
    """Lo único que `ResolutorClavesPostgres` necesita de `EscritorPostgres` (evita el import cruzado)."""

    def registrar_vinculo(self, id_alt_paciente: str, id_paciente: str) -> None: ...

    def resolver_vinculo(self, id_alt_paciente: str) -> str | None: ...

    def es_ambiguo(self, id_alt_paciente: str) -> bool: ...


def resolver_claves(
    identidad: IdentidadCruda,
    pepper: bytes,
    resolutor: ResolutorClavesProtocol,
    *,
    id_documento: str,
    etapa: str,
) -> ClavesPaciente:
    """Resuelve `ClavesPaciente` para un documento; lanza `CLAVE_PII_NO_RESUELTA` si no se puede.
    `id_documento` no se usa en el cálculo, sólo para que el llamador enriquezca el error."""
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
            # Candidatos conflictivos (homónimos): a diferencia de CLAVE_PII_NO_RESUELTA, reprocesar no lo arregla.
            raise ErrorParseo(CodigoErrorDocumento.CLAVE_PII_AMBIGUA, etapa=etapa)

    raise ErrorParseo(CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA, etapa=etapa)
