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


def _aplanar(resultado) -> list[dict]:
    """`resultado.referencias` es ahora una tupla de grupos (cada uno una
    tupla de referencias) -- no una tupla plana. Ver docstring de
    `ResultadoLanzamiento` y openspec `paralelismo-de-procesamiento`."""
    return [referencia for grupo in resultado.referencias for referencia in grupo]


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
    referencias = _aplanar(resultado)

    assert resultado.corrida_id
    # Ambos PDFs quedan sueltos directamente bajo `tmp_path` (sin subcarpeta
    # propia): forman UN solo grupo, corpus plano (ver `listar_grupos`).
    assert len(resultado.referencias) == 1
    assert len(referencias) == 2
    assert all(set(referencia) == {"id_documento", "uri", "sha256"} for referencia in referencias)

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
    referencias = _aplanar(resultado)

    assert len(referencias) == 1  # solo el chico se inventaria
    assert len(cuarentena.registrados) == 1
    (error,) = cuarentena.registrados
    assert error.codigo == CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO
    assert error.corrida_id == resultado.corrida_id


def test_lanzar_persiste_la_transicion_a_inventariando_pero_no_a_procesando(tmp_path) -> None:
    """`lanzar()` sólo inventaría: no encola ni ejecuta nada (el único
    llamador de `procesar_grupo` en todo el repositorio es
    `scripts/procesar_carpeta.py`). Antes avanzaba igual el estado hasta
    `PROCESANDO`, así que una corrida lanzada desde `POST /corridas` quedaba
    diciendo "procesando" para siempre sin que nada la procesara -- un
    silencio de estado. Quien avanza el estado tiene que ser quien hace el
    trabajo; `lanzar()` no lo hace, así que no puede afirmarlo."""
    _pdf(tmp_path, "uno.pdf", b"contenido-uno")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)

    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "inventariando"


def test_lanzar_agrupa_por_subdirectorio_y_la_particion_es_disjunta(tmp_path) -> None:
    """openspec `paralelismo-de-procesamiento` PR 2: `lanzar()` devuelve
    grupos, no una tupla plana -- cada subcarpeta es un grupo (un paciente),
    y ningún documento aparece en dos grupos a la vez."""
    (tmp_path / "paciente-a").mkdir()
    (tmp_path / "paciente-b").mkdir()
    _pdf(tmp_path / "paciente-a", "lab.pdf", b"contenido-a-lab")
    _pdf(tmp_path / "paciente-a", "ecg.pdf", b"contenido-a-ecg")
    _pdf(tmp_path / "paciente-b", "eco.pdf", b"contenido-b-eco")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)

    assert len(resultado.referencias) == 2
    tamanos = sorted(len(grupo) for grupo in resultado.referencias)
    assert tamanos == [1, 2]

    ids_documento = [referencia["id_documento"] for grupo in resultado.referencias for referencia in grupo]
    assert len(ids_documento) == len(set(ids_documento)), "particion disjunta: sin duplicados entre grupos"

    with Session(motor) as sesion:
        documentos = sesion.scalars(
            sa.select(DocumentoCorridaOrm).where(DocumentoCorridaOrm.corrida_id == resultado.corrida_id)
        ).all()
    assert len(documentos) == 3, "particion exhaustiva: el inventario sigue viendo los 3 documentos"


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
