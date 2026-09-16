"""Cruce seguro entre el inventario PDF y los destinos del modelo."""

from __future__ import annotations

from collections.abc import Iterable

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo, EtapaDocumento

from .base import HallazgoCobertura, ReferenciaCampo


def _clave(elemento: HallazgoCobertura | ReferenciaCampo) -> tuple[str, int]:
    return elemento.id_campo, elemento.ordinal


def _primera_clave_duplicada(claves: Iterable[tuple[str, int]]) -> tuple[str, int] | None:
    vistas: set[tuple[str, int]] = set()
    for clave in claves:
        if clave in vistas:
            return clave
        vistas.add(clave)
    return None


def verificar_cobertura(
    inventario: Iterable[HallazgoCobertura], referencias: Iterable[ReferenciaCampo]
) -> tuple[str, ...]:
    """Cruza inventario (PDF) contra referencias (modelo): modelo sin respaldo en PDF es
    terminal; PDF sin citar en el modelo es benigno y se devuelve como `id_campo` repetible."""
    hallazgos = tuple(inventario)
    destinos = tuple(referencias)
    claves_hallazgos = [_clave(hallazgo) for hallazgo in hallazgos]
    claves_destinos = [_clave(referencia) for referencia in destinos]

    repetido = _primera_clave_duplicada(claves_hallazgos)
    if repetido is not None:
        hallazgo = next(hallazgo for hallazgo in hallazgos if _clave(hallazgo) == repetido)
        raise ErrorParseo(CodigoErrorDocumento.COBERTURA_AMBIGUA, EtapaDocumento.RECONCILIACION, hallazgo.id_campo, hallazgo.pagina)

    repetido = _primera_clave_duplicada(claves_destinos)
    if repetido is not None:
        referencia = next(referencia for referencia in destinos if _clave(referencia) == repetido)
        raise ErrorParseo(CodigoErrorDocumento.COBERTURA_AMBIGUA, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)

    # Integridad primero: un dato afirmado sin respaldo manda sobre cualquier hallazgo benigno.
    hallazgos_por_clave = {_clave(hallazgo): hallazgo for hallazgo in hallazgos}
    for referencia in destinos:
        hallazgo = hallazgos_por_clave.get(_clave(referencia))
        if hallazgo is None:
            raise ErrorParseo(CodigoErrorDocumento.COBERTURA_INCOMPLETA, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        if hallazgo.pagina != referencia.pagina:
            # Se reporta la página real de la evidencia, no la que el modelo afirma.
            raise ErrorParseo(CodigoErrorDocumento.COBERTURA_INCOMPLETA, EtapaDocumento.RECONCILIACION, referencia.id_campo, hallazgo.pagina)

    destinos_por_clave = {_clave(referencia): referencia for referencia in destinos}
    campos_no_extraidos: list[str] = []
    for hallazgo in hallazgos:
        referencia = destinos_por_clave.get(_clave(hallazgo))
        if referencia is None or referencia.pagina != hallazgo.pagina:
            campos_no_extraidos.append(hallazgo.id_campo)
    return tuple(campos_no_extraidos)
