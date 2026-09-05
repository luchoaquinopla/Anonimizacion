"""Los dos centinelas que no se pueden fabricar a mano (tasks.md, Fase 8).

1. **Contra la máquina de estados** (Decisión 5): el embudo tiene que dar
   números correctos mientras TODAS las filas de `documento_corrida` siguen
   en `INVENTARIADO` -- si alguien acopla `construir_embudo` a ese estado,
   este test se pone rojo sin que haga falta ningún grep.

2. **De solapamiento, camino real** (Decisión 9): un documento con fila en
   AMBOS destinos sólo es alcanzable por el camino real de reintentos
   agotados -- `escribir_registro` commitea, la conexión se cae, los
   reintentos se agotan, `ERROR_TRANSITORIO_AGOTADO` manda el mismo
   documento a cuarentena con el `estudio` ya escrito. Se corre por
   `EjecutorPipeline.procesar_lote` real (Fase 5), nunca fabricando el
   estado inconsistente insertando filas a mano.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.estados_corrida import EstadoDocumentoCorrida
from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.pipeline.ejecutor import MAX_REINTENTOS, EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento, FalloDocumento
from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.pseudonimizacion.vinculacion import MetadataEpisodio, ResultadoVinculacion
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base, Cuarentena, Estudio
from anonimizacion.salida.modelos_salida import ContenidoLaboratorioSalida
from anonimizacion.web import embudo_corrida
from anonimizacion.web.embudo_corrida import construir_embudo

PEPPER = b"pepper-panel-de-operacion-no-usar-en-produccion"


def _motor_vacio() -> sa.Engine:
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_el_embudo_da_numeros_correctos_con_todo_el_inventario_en_inventariado() -> None:
    """8.9/8.10: el centinela contra la máquina de estados."""
    engine = _motor_vacio()
    repositorio = RepositorioCorridas(engine)
    corrida_id = "corrida-estado-fijo"
    repositorio.crear_corrida(Corrida.crear(corrida_id))

    # Cinco documentos inventariados -- NINGUNO avanza nunca de `INVENTARIADO`,
    # tal como pide Decisión 5: `documento_corrida` es inventario puro.
    documentos = [
        DocumentoCorrida.inventariado(
            corrida_id=corrida_id, huella_contenido=f"huella-{i}", ruta_autorizada=f"/ruta/{i}.pdf"
        )
        for i in range(5)
    ]
    repositorio.registrar_documentos(documentos)

    # Tres publicados, dos apartados -- el embudo cierra sobre esos 5.
    with Session(engine) as sesion, sesion.begin():
        for i in range(3):
            sesion.add(
                Estudio(
                    id_episodio="ep-1",
                    tipo_documento="laboratorio",
                    fecha_estudio=date(2026, 1, 1),
                    precision_hora="ausente",
                    clave_documento=f"clave-{i}",
                    corrida_id=corrida_id,
                )
            )
        for i in range(2):
            sesion.add(
                Cuarentena(
                    id_documento=f"doc-apartado-{i}",
                    etapa="parseo",
                    codigo="parseo_incompleto",
                    corrida_id=corrida_id,
                )
            )

    with Session(engine) as sesion:
        estados = sesion.scalars(
            sa.select(sa.Column("estado")).select_from(sa.text("documento_corrida"))
        ).all()
    assert set(estados) == {EstadoDocumentoCorrida.INVENTARIADO.value}, (
        "el fixture de este test no sirve de centinela si algo ya avanzó el estado"
    )

    embudo = construir_embudo(engine, corrida_id)

    assert embudo.entraron == 5
    assert embudo.publicados == 3
    assert embudo.apartados == 2
    assert embudo.residuo == 0
    assert embudo.cierra is True


@dataclass
class _DestinoConexionCaidaTrasCommit:
    """`escribir_registro` commitea de verdad y LUEGO simula la caída de red.

    El primer intento inserta la fila real de `estudio` (vía el
    `EscritorPostgres` real) y confirma la transacción -- después de eso,
    lanza como si la conexión se hubiera caído antes de que el cliente viera
    el OK. Cada reintento posterior encuentra la fila ya escrita (el `SELECT`
    previo de `EscritorPostgres.escribir_registro` la detecta y no reinserta
    nada) pero la excepción simulada sigue, así que los reintentos igual se
    agotan -- exactamente el camino que describe design.md, Decisión 9.
    """

    real: EscritorPostgres
    intentos: int = field(default=0)

    def escribir_episodio(self, **kwargs: object) -> None:
        self.real.escribir_episodio(**kwargs)  # type: ignore[arg-type]

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        self.intentos += 1
        self.real.escribir_registro(registro)
        raise ConnectionError("conexion caida antes de que el cliente viera el OK")


class _DormirSinEsperar:
    def __init__(self) -> None:
        self.llamadas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.llamadas.append(segundos)


def _documento_laboratorio() -> DocumentoParseado:
    return DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=None,
        fecha_estudio=date(2026, 1, 5),
        contenido=object(),
        adicionales={},
        fuentes=(),
    )


def test_el_solapamiento_se_detecta_por_el_camino_real_de_reintentos_agotados() -> None:
    """8.11/8.12: el centinela de solapamiento -- residuo negativo, sin fabricar nada a mano."""
    engine = _motor_vacio()
    repositorio = RepositorioCorridas(engine)
    corrida_id = "corrida-solapada"
    repositorio.crear_corrida(Corrida.crear(corrida_id))
    repositorio.registrar_documentos(
        [DocumentoCorrida.inventariado(corrida_id=corrida_id, huella_contenido="a" * 64, ruta_autorizada="/r/0.pdf")]
    )

    destino_real = EscritorPostgres(engine)
    destino = _DestinoConexionCaidaTrasCommit(real=destino_real)
    cuarentena = EscritorCuarentena(engine)
    dormir = _DormirSinEsperar()

    def resolver_claves(*args: object, **kwargs: object) -> ClavesPaciente:
        return ClavesPaciente(id_paciente="pid-solape", id_alt_paciente=None, version_clave=1)

    def vincular_episodios(documentos, pepper):  # type: ignore[no-untyped-def]
        return ResultadoVinculacion(
            id_episodio_por_documento={d.id_documento: "ep-solape" for d in documentos},
            metadata_por_episodio={
                "ep-solape": MetadataEpisodio(id_paciente="pid-solape", fecha_ancla=date(2026, 1, 5))
            },
        )

    def construir_registro(documento, claves, *, id_episodio, pepper, clave_documento, motor_pii=None):  # type: ignore[no-untyped-def]
        return RegistroAnonimizado(
            id_paciente=claves.id_paciente,
            id_episodio=id_episodio,
            tipo_documento=documento.tipo_documento,
            version_esquema=documento.version_esquema,
            fecha_estudio=documento.fecha_estudio,
            contenido=ContenidoLaboratorioSalida(id_medico=None, resultados=()),
            clave_documento=clave_documento,
        )

    class _ParseadorFake:
        def parsear(self, texto: object) -> object:
            return texto

    class _ReconciliadorFake:
        def reconciliar(self, documento: object, texto: object) -> None:
            return None

    ejecutor = EjecutorPipeline(
        resolutor=object(),  # type: ignore[arg-type]
        motor=object(),  # type: ignore[arg-type]
        pepper=PEPPER,
        destino=destino,
        cuarentena=cuarentena,
        dormir=dormir,
        extraer=lambda artefacto: _documento_laboratorio(),
        detectar_tipo=lambda texto: TipoDocumento.LABORATORIO,
        obtener_parseador=lambda tipo: _ParseadorFake(),
        obtener_reconciliador=lambda tipo: _ReconciliadorFake(),
        resolver_claves=resolver_claves,
        vincular_episodios=vincular_episodios,
        construir_registro=construir_registro,
        clasificar_pii=lambda documento, motor: None,
        coordinar_episodios=None,
    )

    item = ItemLote(
        id_documento="doc-solape-0",
        artefacto=ArtefactoCrudo(uri="/r/0.pdf", sha256="a" * 64, formato=FormatoArtefacto.PDF),
    )

    resultados = ejecutor.procesar_lote([item], corrida_id=corrida_id)

    # El camino real: se agotan los MAX_REINTENTOS reintentos de `escribir_registro`.
    assert destino.intentos == MAX_REINTENTOS + 1
    assert len(resultados) == 1
    assert isinstance(resultados[0], FalloDocumento)
    assert resultados[0].error.codigo == CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO
    assert resultados[0].error.etapa == "salida"

    with Session(engine) as sesion:
        estudios = sesion.scalars(sa.select(Estudio).where(Estudio.corrida_id == corrida_id)).all()
        cuarentenas = sesion.scalars(sa.select(Cuarentena).where(Cuarentena.corrida_id == corrida_id)).all()
    assert len(estudios) == 1, "el estudio quedo commiteado por el primer intento, antes de la caida simulada"
    assert len(cuarentenas) == 1, "el mismo documento tambien llego a cuarentena por agotar reintentos"

    embudo = construir_embudo(engine, corrida_id)

    assert embudo.entraron == 1
    assert embudo.publicados == 1
    assert embudo.apartados == 1
    assert embudo.residuo == 1 - (1 + 1)
    assert embudo.residuo < 0
    assert embudo.cierra is False


def test_el_residuo_es_cero_al_terminar_una_corrida_sintetica_sin_fallos() -> None:
    """8.13: cierra la invariante tambien en el lado positivo, de punta a punta."""
    engine = _motor_vacio()
    repositorio = RepositorioCorridas(engine)
    corrida_id = "corrida-completa"
    repositorio.crear_corrida(Corrida.crear(corrida_id))
    repositorio.registrar_documentos(
        [
            DocumentoCorrida.inventariado(corrida_id=corrida_id, huella_contenido="b" * 64, ruta_autorizada="/r/1.pdf"),
            DocumentoCorrida.inventariado(corrida_id=corrida_id, huella_contenido="c" * 64, ruta_autorizada="/r/2.pdf"),
        ]
    )

    destino = EscritorPostgres(engine)
    cuarentena = EscritorCuarentena(engine)

    def resolver_claves(*args: object, **kwargs: object) -> ClavesPaciente:
        return ClavesPaciente(id_paciente="pid-completa", id_alt_paciente=None, version_clave=1)

    def vincular_episodios(documentos, pepper):  # type: ignore[no-untyped-def]
        return ResultadoVinculacion(
            id_episodio_por_documento={d.id_documento: "ep-completa" for d in documentos},
            metadata_por_episodio={
                "ep-completa": MetadataEpisodio(id_paciente="pid-completa", fecha_ancla=date(2026, 1, 5))
            },
        )

    def construir_registro(documento, claves, *, id_episodio, pepper, clave_documento, motor_pii=None):  # type: ignore[no-untyped-def]
        return RegistroAnonimizado(
            id_paciente=claves.id_paciente,
            id_episodio=id_episodio,
            tipo_documento=documento.tipo_documento,
            version_esquema=documento.version_esquema,
            fecha_estudio=documento.fecha_estudio,
            contenido=ContenidoLaboratorioSalida(id_medico=None, resultados=()),
            clave_documento=clave_documento,
        )

    class _ParseadorFake:
        def parsear(self, texto: object) -> object:
            return texto

    class _ReconciliadorFake:
        def reconciliar(self, documento: object, texto: object) -> None:
            return None

    ejecutor = EjecutorPipeline(
        resolutor=object(),  # type: ignore[arg-type]
        motor=object(),  # type: ignore[arg-type]
        pepper=PEPPER,
        destino=destino,
        cuarentena=cuarentena,
        dormir=_DormirSinEsperar(),
        extraer=lambda artefacto: _documento_laboratorio(),
        detectar_tipo=lambda texto: TipoDocumento.LABORATORIO,
        obtener_parseador=lambda tipo: _ParseadorFake(),
        obtener_reconciliador=lambda tipo: _ReconciliadorFake(),
        resolver_claves=resolver_claves,
        vincular_episodios=vincular_episodios,
        construir_registro=construir_registro,
        clasificar_pii=lambda documento, motor: None,
        coordinar_episodios=None,
    )

    items = [
        ItemLote(
            id_documento="doc-completa-1",
            artefacto=ArtefactoCrudo(uri="/r/1.pdf", sha256="b" * 64, formato=FormatoArtefacto.PDF),
        ),
        ItemLote(
            id_documento="doc-completa-2",
            artefacto=ArtefactoCrudo(uri="/r/2.pdf", sha256="c" * 64, formato=FormatoArtefacto.PDF),
        ),
    ]

    resultados = ejecutor.procesar_lote(items, corrida_id=corrida_id)
    assert all(isinstance(r, ExitoDocumento) for r in resultados)

    embudo = construir_embudo(engine, corrida_id)
    assert embudo.entraron == 2
    assert embudo.publicados == 2
    assert embudo.apartados == 0
    assert embudo.residuo == 0
    assert embudo.cierra is True


def test_las_consultas_reales_nunca_proyectan_columnas_de_pii() -> None:
    """El chequeo fuerte que pidió la revisión: inspecciona el SQL COMPILADO
    que `construir_embudo` ejecuta de verdad contra un motor real, no los
    nombres de campo de los dataclasses de salida (eso lo cubre el test
    débil en `tests/web/test_embudo_corrida.py`, y dice explícitamente que no
    alcanza). Un futuro `select(Cuarentena)` sin proyección explícita -- que
    trajera `ruta_autorizada`/`huella_contenido` al proceso aunque después no
    se expusieran en el `Embudo` -- pondría este test en rojo.
    """
    engine = _motor_vacio()
    repositorio = RepositorioCorridas(engine)
    corrida_id = "corrida-auditoria-sql"
    repositorio.crear_corrida(Corrida.crear(corrida_id))
    repositorio.registrar_documentos(
        [DocumentoCorrida.inventariado(corrida_id=corrida_id, huella_contenido="d" * 64, ruta_autorizada="/r/pii.pdf")]
    )

    sentencias: list[str] = []

    def _capturar(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        sentencias.append(statement)

    sa.event.listen(engine, "before_cursor_execute", _capturar)
    try:
        embudo_corrida._CACHE.clear()
        construir_embudo(engine, corrida_id)
    finally:
        sa.event.remove(engine, "before_cursor_execute", _capturar)

    assert sentencias, "no se ejecuto ninguna consulta -- este test no probaria nada"
    combinado = " ".join(s.lower() for s in sentencias)
    assert "ruta_autorizada" not in combinado
    assert "huella_contenido" not in combinado
