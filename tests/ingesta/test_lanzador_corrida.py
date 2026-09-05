"""Tests de `LanzadorCorrida`/`CuarentenaDeCorrida` (tasks.md 6.4-6.7).

Único punto donde nace una corrida (design.md, "Recorrido"): crea la fila
`corrida`, inventaría vía `FuenteLocal` y `RepositorioCorridas.registrar_documentos`,
y devuelve `corrida_id` + las referencias listas para `trabajadores.tareas.procesar_grupo`.

`CuarentenaDeCorrida` decora el sumidero de cuarentena para que los artefactos
apartados por sobretamaño en `FuenteLocal` -- que nunca llegan al ejecutor y
por lo tanto nunca pasan por `_a_fallo` -- también queden atribuidos a la
corrida que los intentó ingerir (design.md, "El denominador no es el
inventario: es el inventario más el sobretamaño").
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento
from anonimizacion.ingesta.lanzador_corrida import CuarentenaDeCorrida, LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base, CorridaOrm, DocumentoCorridaOrm


@dataclass
class _CuarentenaFake:
    registrados: list = field(default_factory=list)

    def registrar(self, error: ErrorDocumento) -> None:
        self.registrados.append(error)


def _pdf(directorio, nombre: str, contenido: bytes) -> None:
    (directorio / nombre).write_bytes(contenido)


def _motor_con_esquema():
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    return motor


def test_lanzador_crea_la_corrida_inventaria_y_devuelve_referencias(tmp_path) -> None:
    """6.4: falla porque `LanzadorCorrida` no existe."""
    _pdf(tmp_path, "uno.pdf", b"contenido-uno")
    _pdf(tmp_path, "dos.pdf", b"contenido-dos")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)

    assert resultado.corrida_id
    assert len(resultado.referencias) == 2
    assert all(set(referencia) == {"id_documento", "uri", "sha256"} for referencia in resultado.referencias)

    with Session(motor) as sesion:
        assert sesion.get(CorridaOrm, resultado.corrida_id) is not None
        documentos = sesion.scalars(
            sa.select(DocumentoCorridaOrm).where(DocumentoCorridaOrm.corrida_id == resultado.corrida_id)
        ).all()
    assert len(documentos) == 2


def test_lanzar_dos_veces_produce_dos_corridas_independientes(tmp_path) -> None:
    _pdf(tmp_path, "uno.pdf", b"contenido-uno")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    primero = lanzador.lanzar(tmp_path)
    segundo = lanzador.lanzar(tmp_path)

    assert primero.corrida_id != segundo.corrida_id
    with Session(motor) as sesion:
        documentos = sesion.scalars(sa.select(DocumentoCorridaOrm)).all()
    assert len(documentos) == 2, "cada corrida inventaria su propia copia -- son corridas distintas"


def test_artefacto_sobretamano_llega_a_cuarentena_con_el_corrida_id_de_la_corrida(tmp_path) -> None:
    """6.6: falla porque `CuarentenaDeCorrida` no existe -- sin ella el
    artefacto sobretamaño se aparta con `corrida_id=None`."""
    _pdf(tmp_path, "chico.pdf", b"contenido-chico")
    _pdf(tmp_path, "grande.pdf", b"X" * 200)

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    cuarentena = _CuarentenaFake()
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=cuarentena, tope_bytes=50)

    resultado = lanzador.lanzar(tmp_path)

    assert len(resultado.referencias) == 1  # solo el chico se inventaria
    assert len(cuarentena.registrados) == 1
    (error,) = cuarentena.registrados
    assert error.codigo == CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO
    assert error.corrida_id == resultado.corrida_id


def test_cuarentena_de_corrida_estampa_corrida_id_sin_pisar_el_resto_del_error() -> None:
    """Unidad, sin `LanzadorCorrida`: `CuarentenaDeCorrida.registrar` delega en
    el sumidero interno con el mismo `ErrorDocumento`, solo con `corrida_id` fijado."""
    interna = _CuarentenaFake()
    decorado = CuarentenaDeCorrida(interna=interna, corrida_id="c1")
    original = ErrorDocumento(
        id_documento="doc-1",
        etapa="ingesta",
        codigo=CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO,
        tamano_bytes=999,
        tope_bytes=100,
    )

    decorado.registrar(original)

    (registrado,) = interna.registrados
    assert registrado.corrida_id == "c1"
    assert registrado.id_documento == original.id_documento
    assert registrado.tamano_bytes == original.tamano_bytes
    assert registrado.tope_bytes == original.tope_bytes
