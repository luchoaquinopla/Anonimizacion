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

import socket
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorDocumento
from anonimizacion.ingesta.lanzador_corrida import CuarentenaDeCorrida, LanzadorCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.salida.modelos_orm import Base, CorridaOrm, DocumentoCorridaOrm, Episodio, Estudio

# Ver el comentario junto a `_CONNECT_REAL` en
# `tests/scripts/test_procesar_carpeta.py`: captura la implementación real
# ANTES de que `tests/conftest.py::_bloquear_llamadas_de_red_reales` la
# parchee a nivel de sesión.
_CONNECT_REAL = socket.socket.connect
_URL_POSTGRES_REAL = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"


@dataclass
class _CuarentenaFake:
    registrados: list = field(default_factory=list)

    def registrar(self, error: ErrorDocumento) -> None:
        self.registrados.append(error)


def _pdf(directorio, nombre: str, contenido: bytes) -> None:
    (directorio / nombre).write_bytes(contenido)


def _materializar(resultado) -> list[tuple[dict, ...]]:
    """`resultado.referencias` es un ITERADOR de grupos de UN SOLO USO
    (revisión adversarial, hallazgo crítico 2 -- ya no es ni siquiera una
    tupla materializada). Los tests SÍ pueden pagar el costo de
    materializarlo una vez para poder asertar `len()`/indexar varias veces
    sobre el resultado -- lo que no puede hacer es el LLAMADOR DE PRODUCCIÓN
    (`scripts/procesar_carpeta.py`), que consume cada grupo a medida que lo
    despacha. Ver docstring de `ResultadoLanzamiento`."""
    return list(resultado.referencias)


def _aplanar(resultado) -> list[dict]:
    """Igual que `_materializar`, pero además aplana los grupos en una sola
    lista de referencias -- para tests que sólo necesitan el conteo total."""
    return [referencia for grupo in _materializar(resultado) for referencia in grupo]


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
    grupos = _materializar(resultado)
    referencias = [referencia for grupo in grupos for referencia in grupo]

    assert resultado.corrida_id
    # Ambos PDFs quedan sueltos directamente bajo `tmp_path` (sin subcarpeta
    # propia): forman UN solo grupo, corpus plano (ver `listar_grupos`).
    assert len(grupos) == 1
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
    _materializar(primero)  # drena el generador: dispara el registro en DB (ver docstring)
    segundo = lanzador.lanzar(tmp_path)
    _materializar(segundo)

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
    grupos = _materializar(resultado)

    assert len(grupos) == 2
    tamanos = sorted(len(grupo) for grupo in grupos)
    assert tamanos == [1, 2]

    ids_documento = [referencia["id_documento"] for grupo in grupos for referencia in grupo]
    assert len(ids_documento) == len(set(ids_documento)), "particion disjunta: sin duplicados entre grupos"

    with Session(motor) as sesion:
        documentos = sesion.scalars(
            sa.select(DocumentoCorridaOrm).where(DocumentoCorridaOrm.corrida_id == resultado.corrida_id)
        ).all()
    assert len(documentos) == 3, "particion exhaustiva: el inventario sigue viendo los 3 documentos"


def test_lanzar_es_perezoso_no_materializa_la_particion_completa(
    tmp_path, monkeypatch
) -> None:
    """Revisión adversarial, hallazgo crítico 2: `lanzar()` hacía
    `grupos = list(fuente.listar_grupos())` antes de devolver
    `ResultadoLanzamiento` -- retenía la partición COMPLETA en memoria antes
    de que el llamador pudiera despachar el primer grupo, mudando a este
    punto el mismo problema de RAM que `listar_grupos()` resuelve. Consumir
    sólo el primer grupo de `resultado.referencias` NO debe hashear los
    archivos de carpetas posteriores (salvo el lookahead mínimo de
    `itertools.groupby`, igual que en `FuenteLocal.listar_grupos`)."""
    from anonimizacion.ingesta.fuente import FuenteLocal

    for nombre_paciente in ("paciente-a", "paciente-b", "paciente-c"):
        carpeta = tmp_path / nombre_paciente
        carpeta.mkdir()
        for indice in range(2):
            _pdf(carpeta, f"doc{indice}.pdf", f"contenido-{nombre_paciente}-{indice}".encode())

    original = FuenteLocal._calcular_huella
    llamados: list[str] = []

    def _huella_contada(ruta):
        llamados.append(str(ruta))
        return original(ruta)

    monkeypatch.setattr(FuenteLocal, "_calcular_huella", staticmethod(_huella_contada))

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)
    next(resultado.referencias)  # consumir SOLO el primer grupo

    assert not any("paciente-c" in ruta for ruta in llamados)


def test_lanzar_referencias_iterada_dos_veces_falla_ruidoso(tmp_path) -> None:
    """Salvaguarda estructural (revisión adversarial, MEDIO): antes de esto,
    nada impedía que un consumidor futuro iterara `resultado.referencias` dos
    veces y perdiera todos los grupos en silencio la segunda vez (un
    generador agotado simplemente no produce nada más). Ahora la segunda
    iteración explota con `RuntimeError` en vez de devolver una secuencia
    vacía sin avisar."""
    (tmp_path / "paciente-a").mkdir()
    _pdf(tmp_path / "paciente-a", "lab.pdf", b"contenido-a-lab")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)  # primer consumo: agota el iterador

    with pytest.raises(RuntimeError, match="un solo uso"):
        list(resultado.referencias)  # segundo consumo: debe fallar, no devolver []


def test_marcar_finalizada_cierra_procesando_sin_pasar_por_reconciliando(tmp_path) -> None:
    """Feature `despachador-desde-el-panel`: quien de verdad despachó y
    terminó de procesar el inventario (el despachador desde el panel, hoy
    `ServicioCorridasReal`) tiene que poder cerrar la corrida -- misma regla
    de `marcar_procesando`: quien avanza el estado tiene que ser quien hizo
    el trabajo."""
    _pdf(tmp_path, "uno.pdf", b"contenido-uno")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)
    lanzador.marcar_procesando(resultado.corrida_id)

    lanzador.marcar_finalizada(resultado.corrida_id, hubo_cuarentena=False)

    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "completada"


def test_marcar_finalizada_con_cuarentena_usa_el_estado_correspondiente(tmp_path) -> None:
    _pdf(tmp_path, "uno.pdf", b"contenido-uno")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)
    lanzador.marcar_procesando(resultado.corrida_id)

    lanzador.marcar_finalizada(resultado.corrida_id, hubo_cuarentena=True)

    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "completada_con_cuarentena"


def test_marcar_finalizada_de_corrida_inexistente_falla_ruidoso() -> None:
    """Mismo contrato que `marcar_procesando`: no hay forma de finalizar una
    corrida que no existe."""
    motor = _motor_con_esquema()
    lanzador = LanzadorCorrida(repositorio=RepositorioCorridas(motor), cuarentena=_CuarentenaFake())

    with pytest.raises(ValueError, match="no existe una corrida"):
        lanzador.marcar_finalizada("corrida-fantasma", hubo_cuarentena=False)


def test_marcar_fallida_cierra_procesando_como_fallida(tmp_path) -> None:
    """Feature `despachador-desde-el-panel`: si el despacho en segundo plano
    lanza una excepción INESPERADA (no una cuarentena por documento, que
    `despachar_en_paralelo` nunca propaga -- algo que rompe el hilo entero),
    quien orquesta el despacho tiene que poder cerrar la corrida como
    `FALLIDA` en vez de dejarla `procesando` para siempre."""
    _pdf(tmp_path, "uno.pdf", b"contenido-uno")

    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())

    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)
    lanzador.marcar_procesando(resultado.corrida_id)

    lanzador.marcar_fallida(resultado.corrida_id)

    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "fallida"


_MARGEN_PRUEBA = timedelta(minutes=15)


def test_recuperar_corridas_abandonadas_cierra_toda_corrida_no_terminal_sin_evidencia_reciente(tmp_path) -> None:
    """Feature `despachador-desde-el-panel`: al arrancar el servidor, una
    corrida en estado no terminal SIN evidencia reciente de trabajo (ver
    `RepositorioCorridas.ultima_actividad`) es una corrida abandonada por un
    proceso anterior. Dejarla en su estado no terminal repetiría la misma
    mentira que `fix/silencios-de-ingesta-y-panel` cerró en la punta de
    arranque, y además bloquearía para siempre el gate de "una corrida a la
    vez" (`listar_corridas_no_terminales`), sacando al operador de su propio
    panel.

    `ahora` se inyecta bien en el futuro (revisión adversarial crítico 1):
    sin esto, `corrida.actualizada_en` (recién escrita por este mismo test)
    siempre estaría dentro de CUALQUIER margen razonable, y el test no
    probaría nada sobre el paso del tiempo."""
    from anonimizacion.ingesta.lanzador_corrida import recuperar_corridas_abandonadas

    _pdf(tmp_path, "uno.pdf", b"contenido-uno")
    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())
    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)  # queda en INVENTARIANDO -- "abandonada" tras un crash simulado

    mucho_despues = datetime.now(timezone.utc) + timedelta(days=1)
    recuperados = recuperar_corridas_abandonadas(repositorio, margen_inactividad=_MARGEN_PRUEBA, ahora=mucho_despues)

    assert recuperados == [resultado.corrida_id]
    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "fallida"


def test_recuperar_corridas_abandonadas_no_toca_corridas_ya_cerradas(tmp_path) -> None:
    from anonimizacion.ingesta.lanzador_corrida import recuperar_corridas_abandonadas

    _pdf(tmp_path, "uno.pdf", b"contenido-uno")
    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())
    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)
    lanzador.marcar_procesando(resultado.corrida_id)
    lanzador.marcar_finalizada(resultado.corrida_id, hubo_cuarentena=False)

    mucho_despues = datetime.now(timezone.utc) + timedelta(days=1)
    recuperados = recuperar_corridas_abandonadas(repositorio, margen_inactividad=_MARGEN_PRUEBA, ahora=mucho_despues)

    assert recuperados == []
    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "completada"


def test_recuperar_corridas_abandonadas_no_toca_una_corrida_viva_en_otro_proceso(tmp_path) -> None:
    """Revisión adversarial crítico 1 -- reproduce el escenario real:
    `scripts/procesar_carpeta.py` (OTRO proceso, mismo `LanzadorCorrida`,
    misma base) sigue escribiendo `Estudio` bajo un `corrida_id` que nunca va
    a llamar `marcar_finalizada`/`marcar_fallida` -- ese es su comportamiento
    NORMAL, no un bug. Si el panel arranca en ese momento, la recuperación de
    arranque NO puede marcarla `FALLIDA`: sería la inversión exacta del
    defecto que cerró el PR #33 (antes "procesando" sin que nada procese,
    ahora "fallida" mientras algo sí procesa) -- y además reabriría el gate
    de "una corrida a la vez" para una segunda corrida que duplicaría el
    presupuesto de memoria de la que sigue viva."""
    from anonimizacion.ingesta.lanzador_corrida import recuperar_corridas_abandonadas

    _pdf(tmp_path, "uno.pdf", b"contenido-uno")
    motor = _motor_con_esquema()
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())
    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)
    lanzador.marcar_procesando(resultado.corrida_id)  # como haría procesar_carpeta.py

    ahora = datetime.now(timezone.utc)
    # "El script sigue escribiendo": un Estudio real, reciente, bajo esta
    # corrida -- sin que NADA haya llamado marcar_finalizada/marcar_fallida,
    # exactamente el estado en el que procesar_carpeta.py deja la corrida
    # mientras sigue corriendo.
    #
    # CORRECCIÓN (revisión adversarial, ronda 3): la versión anterior
    # insertaba este `Estudio` SIN crear su `Episodio` padre primero.
    # `Estudio.id_episodio` es un FK real contra `episodio.id_episodio`
    # (`modelos_orm.py`) -- SQLite no impone claves foráneas por defecto y lo
    # dejaba pasar en silencio, así que este test JAMÁS podía correr contra
    # Postgres real (`ForeignKeyViolation`). El test que respalda la
    # corrección de un crítico tiene que poder correr en el motor que la
    # corrección dice proteger -- ver
    # `test_recuperar_corridas_abandonadas_no_toca_una_corrida_viva_en_otro_proceso_postgres_real`
    # más abajo, la misma reproducción contra Postgres de verdad.
    with Session(motor) as sesion, sesion.begin():
        sesion.add(Episodio(id_episodio="ep-viva-1", id_paciente="paciente-viva-1", fecha_ancla=date(2024, 1, 1)))
        sesion.add(
            Estudio(
                id_episodio="ep-viva-1",
                tipo_documento="laboratorio",
                fecha_estudio=date(2024, 1, 1),
                precision_hora="ausente",
                clave_documento="clave-corrida-viva-1",
                corrida_id=resultado.corrida_id,
                creado_en=ahora - timedelta(minutes=2),
            )
        )

    # El panel arranca 5 minutos después, con un margen de 15 -- la evidencia
    # de hace 2 minutos sigue dentro del margen.
    recuperados = recuperar_corridas_abandonadas(
        repositorio, margen_inactividad=_MARGEN_PRUEBA, ahora=ahora + timedelta(minutes=5)
    )

    assert recuperados == [], "una corrida con evidencia reciente de otro proceso NO se toca"
    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "procesando", "el arranque del panel no puede pisar el trabajo real de otro proceso"


@pytest.fixture()
def _engine_postgres_real(monkeypatch: pytest.MonkeyPatch):
    """Motor contra el Postgres real de `docker-compose.yml`, o `skip` si no
    responde -- mismo patrón que `tests/scripts/test_procesar_carpeta.py`."""
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    sonda = sa.create_engine(_URL_POSTGRES_REAL, connect_args={"connect_timeout": 3})
    try:
        with sonda.connect():
            pass
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexion es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_REAL}: {excepcion}")
    finally:
        sonda.dispose()

    engine = construir_engine_postgres(_URL_POSTGRES_REAL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.mark.postgres
def test_recuperar_corridas_abandonadas_no_toca_una_corrida_viva_en_otro_proceso_postgres_real(
    tmp_path, _engine_postgres_real
) -> None:
    """Revisión adversarial, ronda 3: la misma reproducción de arriba, pero
    contra Postgres real -- exactamente el motor que la corrección dice
    proteger, con sus claves foráneas reales impuestas. "Antes de decir que
    algo está probado, correlo contra Postgres": si este test no hubiera
    existido, el bug de fixture (Estudio sin Episodio) habría quedado
    invisible para siempre detrás de SQLite."""
    from anonimizacion.ingesta.lanzador_corrida import recuperar_corridas_abandonadas

    motor = _engine_postgres_real
    _pdf(tmp_path, "uno.pdf", b"contenido-uno")
    repositorio = RepositorioCorridas(motor)
    lanzador = LanzadorCorrida(repositorio=repositorio, cuarentena=_CuarentenaFake())
    resultado = lanzador.lanzar(tmp_path)
    _materializar(resultado)
    lanzador.marcar_procesando(resultado.corrida_id)

    ahora = datetime.now(timezone.utc)
    with Session(motor) as sesion, sesion.begin():
        sesion.add(
            Episodio(id_episodio="ep-viva-pg-1", id_paciente="paciente-viva-pg-1", fecha_ancla=date(2024, 1, 1))
        )
        sesion.add(
            Estudio(
                id_episodio="ep-viva-pg-1",
                tipo_documento="laboratorio",
                fecha_estudio=date(2024, 1, 1),
                precision_hora="ausente",
                clave_documento="clave-corrida-viva-pg-1",
                corrida_id=resultado.corrida_id,
                creado_en=ahora - timedelta(minutes=2),
            )
        )

    recuperados = recuperar_corridas_abandonadas(
        repositorio, margen_inactividad=_MARGEN_PRUEBA, ahora=ahora + timedelta(minutes=5)
    )

    assert recuperados == [], "una corrida con evidencia reciente de otro proceso NO se toca (Postgres real)"
    with Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, resultado.corrida_id)
    assert fila.estado == "procesando"


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
