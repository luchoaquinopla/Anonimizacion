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
    """Cruza inventario (PDF) contra referencias (modelo) en sus dos direcciones.

    Dirección modelo->PDF ("el modelo afirma algo que el PDF no respalda"):
    problema de integridad, sigue siendo `ErrorParseo(COBERTURA_INCOMPLETA)`
    -- terminal, va a cuarentena, sin excepción. Publicar ese dato sería
    publicar algo falso.

    Dirección PDF->modelo ("el PDF trae algo que el modelo no citó"): caso
    benigno -- lo que sí se publica es correcto, sólo incompleto. En vez de
    lanzar, esta función DEVUELVE el `id_campo` de cada hallazgo sin destino
    como `CAMPO_NO_EXTRAIDO` (ver dominio/errores.py); el llamador lo agrega
    a la marca de completitud del registro publicado. Un mismo `id_campo`
    puede repetirse en el resultado -- una ocurrencia por hallazgo sin
    destino, no un conjunto -- para que colecciones como
    `laboratorio.resultado` reporten CUÁNTAS instancias faltaron, no sólo
    que faltó "alguna".

    `COBERTURA_AMBIGUA` (claves duplicadas de cualquiera de los dos lados)
    sigue siendo terminal en ambos casos: una clave repetida significa que
    pudimos haber mapeado un valor a la fila equivocada, que es en sí mismo
    un problema de integridad, no de cobertura incompleta.
    """
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

    # Integridad primero (design.md conservador: ante la duda, cuarentena):
    # si hay CUALQUIER dato que el modelo afirma y el PDF no respalda, ese
    # problema manda sobre cualquier hallazgo benigno que se haya juntado
    # abajo -- el documento entero va a cuarentena y `campos_no_extraidos`
    # nunca llega a devolverse.
    hallazgos_por_clave = {_clave(hallazgo): hallazgo for hallazgo in hallazgos}
    for referencia in destinos:
        hallazgo = hallazgos_por_clave.get(_clave(referencia))
        if hallazgo is None:
            raise ErrorParseo(CodigoErrorDocumento.COBERTURA_INCOMPLETA, EtapaDocumento.RECONCILIACION, referencia.id_campo, referencia.pagina)
        if hallazgo.pagina != referencia.pagina:
            # Hay evidencia en el PDF para esta clave, pero en otra página que
            # la que el modelo afirma -- se reporta `hallazgo.pagina` (dónde
            # está la evidencia real), no `referencia.pagina` (dónde el
            # modelo dice, erróneamente, que está).
            raise ErrorParseo(CodigoErrorDocumento.COBERTURA_INCOMPLETA, EtapaDocumento.RECONCILIACION, referencia.id_campo, hallazgo.pagina)

    destinos_por_clave = {_clave(referencia): referencia for referencia in destinos}
    campos_no_extraidos: list[str] = []
    for hallazgo in hallazgos:
        referencia = destinos_por_clave.get(_clave(hallazgo))
        if referencia is None or referencia.pagina != hallazgo.pagina:
            campos_no_extraidos.append(hallazgo.id_campo)
    return tuple(campos_no_extraidos)
