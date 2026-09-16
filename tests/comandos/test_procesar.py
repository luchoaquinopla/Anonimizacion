"""Tests de `scripts/procesar_carpeta.py` (tasks.md 6.8-6.9, PR 2.5).

Confirma que el script ya no arma `FuenteLocal`/`ItemLote` a mano ni llama
`ejecutor.procesar_lote(items)` sin corrida: usa `LanzadorCorrida` para
inventariar y `trabajadores.tareas.procesar_grupo` -- la misma tarea Celery
real que despachara producción (design.md, "Recorrido":
`LanzadorCorrida.lanzar` -> `procesar_grupo(corrida_id, referencias)` ->
`procesar_lote(items, corrida_id=...)`) -- para procesar. Sin este cambio
`LanzadorCorrida`/`CuarentenaDeCorrida` (Fase 6.4-6.7, ya mergeadas) no
tienen ningún llamador de producción.

También demuestra de punta a punta, desde el script, el caso que justifica
`CuarentenaDeCorrida` en vez de estado de corrida en `FuenteLocal`: un
artefacto apartado por sobretamaño -- ANTES de que se calcule su huella, así
que nunca puede inventariarse -- igual queda atribuido a su corrida.
"""

from __future__ import annotations

import importlib.util
import os
import socket
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.dominio.estados_corrida import EstadoCorrida
from anonimizacion.pii.motor import MotorPii
from anonimizacion.salida.destinos.postgres import construir_engine_postgres
from anonimizacion.salida.modelos_orm import Base, CorridaOrm, Cuarentena, Estudio
from anonimizacion.trabajadores import tareas

from ..fixtures.v1 import documentos

_RUTA_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "procesar_carpeta.py"

PEPPER = b"pepper-test-procesar-carpeta-nunca-real"

# Ver `tests/integracion/test_postgres_carrera_real.py` para el porqué de
# capturar esto a nivel de módulo, ANTES de que
# `tests/conftest.py::_bloquear_llamadas_de_red_reales` (autouse, sesión)
# parchee `socket.socket.connect`.
_CONNECT_REAL = socket.socket.connect
_URL_POSTGRES_REAL = "postgresql+psycopg://anonimizacion:anonimizacion_dev@localhost:5433/anonimizacion"


def _cargar_script():
    """Carga `scripts/procesar_carpeta.py` por ruta -- `scripts/` no es un paquete instalado."""
    spec = importlib.util.spec_from_file_location("_procesar_carpeta_bajo_prueba", _RUTA_SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


@pytest.fixture(autouse=True)
def _resetear_fabrica_ejecutor():
    yield
    tareas._fabrica_ejecutor = None


def _grupo_completo(
    directorio,
    sufijo: str,
    *,
    dni: str = "20555888",
    nombre: str = "Ana Sintetica Grupo",
    fecha_nac_lab: str = "05/05/1992",
    fecha_nac_ecg: str = "05-MAY-1992",
):
    """Los tres estudios de un mismo paciente sintético: un episodio completo.

    Prefijos numéricos en el nombre de archivo (no `lab-`/`ecg-`/`eco-` solos):
    `LanzadorCorrida` inventaría vía `FuenteLocal.listar()`, que orderna por
    `sorted(rglob("*"))` -- alfabético por ruta, no por orden de escritura.
    `procesar_lote` resuelve identidad en ESE orden, y el ECG (sin DNI) necesita
    el puente que solo registra el laboratorio (con DNI) al resolverse primero
    (`resolutor_claves.py::resolver_claves`). Sin el prefijo, "ecg-" ordena antes
    que "lab-" y el ECG cae en `CLAVE_PII_NO_RESUELTA` antes de que el
    laboratorio del mismo lote llegue a registrar el puente.

    `dni`/`nombre`/`fecha_nac_*` son parametrizables (revisión adversarial):
    antes `dni` estaba hardcodeado a "20555888" sin importar `sufijo`, así que
    dos llamadas a esta función para "dos pacientes distintos" en realidad
    describían AL MISMO paciente (mismo DNI -> mismo HMAC -> mismo
    `id_paciente`). Un test que interpretó esa colisión de fixture como un
    hallazgo de producción quedó corregido -- ver
    `test_el_script_despacha_dos_pacientes_distintos_en_grupos_separados`.
    `nombre`/`fecha_nac_*` también deben variar junto con `dni` para dos
    pacientes genuinamente distintos: el ECG (sin DNI) resuelve su identidad
    por nombre+fecha_nac contra el puente que dejó el laboratorio -- si dos
    DNI distintos comparten nombre+fecha_nac, son homónimos para el
    resolutor (`CLAVE_PII_AMBIGUA`), no personas distinguibles.
    """
    return [
        documentos.escribir_pdf(
            directorio,
            f"01-lab-{sufijo}",
            documentos.texto_laboratorio(
                nombre=nombre,
                dni=dni,
                fecha_nac=fecha_nac_lab,
                numero_peticion=f"PET-{sufijo}",
                fecha="10/01/2024",
            ),
        ),
        documentos.escribir_pdf(
            directorio,
            f"02-ecg-{sufijo}",
            documentos.texto_ecg(
                nombre=nombre,
                id_estudio=f"ECG-{sufijo}",
                fecha="11-JAN-2024",
                fecha_nac=fecha_nac_ecg,
                edad_anios=31,
                sexo="Female",
            ),
        ),
        documentos.escribir_pdf(
            directorio,
            f"03-eco-{sufijo}",
            documentos.texto_eco(
                nombre=nombre,
                dni=dni,
                numero_estudio=f"ECO-{sufijo}",
                fecha="12/01/2024",
            ),
        ),
    ]


def test_el_script_usa_lanzador_corrida_y_propaga_corrida_id_hasta_el_procesamiento(
    tmp_path, motor: MotorPii
) -> None:
    """6.8: falla hoy -- el script arma `FuenteLocal`/`ItemLote` a mano y llama
    `ejecutor.procesar_lote(items)` sin ningún `corrida_id`, así que no existe
    ninguna fila `corrida` ni `corrida_id` en `estudio` al terminar."""
    _grupo_completo(tmp_path, "s1")

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 0
    with Session(engine) as sesion:
        corridas = sesion.scalars(sa.select(CorridaOrm)).all()
        assert len(corridas) == 1, "el script debe lanzar la corrida vía LanzadorCorrida"

        estudios = sesion.scalars(sa.select(Estudio)).all()
    assert len(estudios) == 3
    assert all(
        estudio.corrida_id == corridas[0].id_corrida for estudio in estudios
    ), "corrida_id debe llegar hasta el procesamiento real, no quedar en None"


def test_el_script_deja_la_corrida_en_procesando_porque_es_quien_procesa(tmp_path, motor: MotorPii) -> None:
    """`LanzadorCorrida.lanzar()` sólo inventaría (ver `test_lanzador_corrida.py`).
    Este script es quien de verdad llama a `procesar_grupo`, así que es quien
    debe afirmar `PROCESANDO` -- inventariar y procesar son cosas distintas, y
    el que sólo inventaría no puede afirmar que está procesando.

    NO verifica el estado FINAL (antes lo hacía, y ese assert enmascaraba el
    CRÍTICO 1 de la revisión adversarial: una corrida que TERMINÓ bien
    quedaba en `PROCESANDO` para siempre, porque nada llamaba
    `marcar_finalizada`). Ver `test_el_script_cierra_la_corrida_como_completada_al_terminar_con_exito`
    para el estado final correcto; este test se queda con lo que sí puede
    afirmar sin instrumentación adicional: que la transición a `PROCESANDO`
    ocurrió en algún momento (evidenciado porque, si no ocurriera, la
    corrida jamás podría llegar a `COMPLETADA` -- `PROCESANDO -> COMPLETADA`
    es la única transición válida hacia ese estado, ver `dominio/corridas.py`)."""
    _grupo_completo(tmp_path, "s3")

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 0
    with Session(engine) as sesion:
        (corrida,) = sesion.scalars(sa.select(CorridaOrm)).all()
    assert corrida.estado in (EstadoCorrida.COMPLETADA.value, EstadoCorrida.COMPLETADA_CON_CUARENTENA.value)


# --- revisión adversarial, CRÍTICO 1: el script nunca cerraba sus corridas -


def test_el_script_cierra_la_corrida_como_completada_al_terminar_con_exito(tmp_path, motor: MotorPii) -> None:
    """Reproducido contra Postgres real (ver el test `_contra_postgres_real`
    más abajo) y acá en SQLite para feedback rápido: `ejecutar()` llamaba
    `lanzador.marcar_procesando(...)` pero NUNCA `marcar_finalizada`/
    `marcar_fallida` al terminar -- a diferencia de `web/servicio_corridas.py`,
    que sí cierra sus corridas (`_despachar_y_cerrar`). Antes del gate de
    "una corrida a la vez" (`ux_corrida_una_activa`, ya en `main`) esto era
    inofensivo; con el gate, CUALQUIER corrida procesada por este script deja
    la fila `activa=true` para siempre y bloquea la siguiente invocación."""
    _grupo_completo(tmp_path, "cierre-exito")

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 0
    with Session(engine) as sesion:
        (corrida,) = sesion.scalars(sa.select(CorridaOrm)).all()
    assert corrida.estado == EstadoCorrida.COMPLETADA.value, (
        "la corrida tiene que quedar en un estado TERMINAL -- si queda PROCESANDO, "
        "bloquea toda invocación futura del script (ux_corrida_una_activa)"
    )


def test_el_script_cierra_como_completada_con_cuarentena_si_hubo_cuarentena(tmp_path, motor: MotorPii) -> None:
    """Escenario "en banda", no el de sobretamaño (`test_el_apartado_por_sobretamano_...`
    más abajo): ese artefacto se aparta ANTES de hashear -- vía
    `CuarentenaDeCorrida`, nunca pasa por `procesar_grupo` -- así que nunca
    aparece en `resultados`, la misma fuente que usa `hubo_cuarentena` tanto
    acá como en `web/servicio_corridas.py::_despachar_y_cerrar` (mismo
    límite conocido en los dos lugares, fuera de alcance de este arreglo).
    Un episodio INCOMPLETO (falta ECG y ECO) sí se clasifica DENTRO de
    `procesar_grupo` y aparece en `resultados` con `estado != "exito"`."""
    documentos.escribir_pdf(
        tmp_path,
        "01-lab-incompleto",
        documentos.texto_laboratorio(
            nombre="Paciente Incompleto",
            dni="20777000",
            fecha_nac="01/01/1990",
            numero_peticion="PET-incompleto",
            fecha="10/01/2024",
        ),
    )

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 0
    with Session(engine) as sesion:
        (corrida,) = sesion.scalars(sa.select(CorridaOrm)).all()
    assert corrida.estado == EstadoCorrida.COMPLETADA_CON_CUARENTENA.value


def test_el_script_cierra_como_fallida_si_no_hay_pdfs(tmp_path, motor: MotorPii) -> None:
    """La carpeta vacía deja la corrida en `INVENTARIANDO` (nunca llega a
    `marcar_procesando`, porque no hay nada que procesar) -- ANTES de este
    arreglo, ese `return 1` temprano tampoco cerraba la corrida. Es una
    transición válida (`INVENTARIANDO -> FALLIDA`, ver `dominio/corridas.py`).

    `motor` sigue siendo obligatorio aunque la carpeta esté vacía:
    `_configurar_ejecutor_secuencial` arma la fábrica ANTES de que
    `lanzador.lanzar()` siquiera empiece a inventariar (ver `ejecutar()`)."""
    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 1
    with Session(engine) as sesion:
        (corrida,) = sesion.scalars(sa.select(CorridaOrm)).all()
    assert corrida.estado == EstadoCorrida.FALLIDA.value


def test_el_script_cierra_como_fallida_si_el_despacho_explota_y_repropaga(
    tmp_path, motor: MotorPii, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simétrico de `web/servicio_corridas.py::_despachar_y_cerrar`: una
    excepción INESPERADA durante el despacho tiene que cerrar la corrida
    como `FALLIDA` (no dejarla en `PROCESANDO` para siempre) Y seguir
    propagándose -- cerrar la corrida no debe tragarse el error real."""
    _grupo_completo(tmp_path, "cierre-excepcion")

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    def _explota(*_args, **_kwargs):
        raise RuntimeError("fallo inesperado simulado en el despacho")

    monkeypatch.setattr(modulo.tareas, "procesar_grupo", _explota)

    with pytest.raises(RuntimeError, match="fallo inesperado simulado"):
        modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    with Session(engine) as sesion:
        (corrida,) = sesion.scalars(sa.select(CorridaOrm)).all()
    assert corrida.estado == EstadoCorrida.FALLIDA.value


def test_el_script_permite_lanzar_una_segunda_corrida_sobre_otra_carpeta_despues_de_la_primera(
    tmp_path, motor: MotorPii
) -> None:
    """EL regression test del CRÍTICO 1: el escenario real es el instituto
    corriendo `anonimizacion procesar --entrada <carpeta>` carpeta tras
    carpeta sobre 5 TB. Reproducido: antes de este arreglo, la SEGUNDA
    llamada a `ejecutar()` -- sobre una carpeta DISTINTA, con el mismo
    engine -- fallaba con `CorridaEnCursoError` aunque la primera hubiera
    terminado con total éxito, porque la primera corrida nunca se cerraba."""
    carpeta_1 = tmp_path / "carpeta-1"
    carpeta_2 = tmp_path / "carpeta-2"
    carpeta_1.mkdir()
    carpeta_2.mkdir()
    _grupo_completo(carpeta_1, "seg-1", dni="20555888", nombre="Ana Sintetica Uno")
    _grupo_completo(
        carpeta_2, "seg-2", dni="20666999", nombre="Beatriz Sintetica Dos",
        fecha_nac_lab="10/10/1985", fecha_nac_ecg="10-OCT-1985",
    )

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    primero = modulo.ejecutar(entrada=carpeta_1, engine=engine, motor=motor, pepper=PEPPER)
    segundo = modulo.ejecutar(entrada=carpeta_2, engine=engine, motor=motor, pepper=PEPPER)

    assert primero == 0
    assert segundo == 0, "la segunda corrida no debe bloquearse por una primera que ya terminó bien"
    with Session(engine) as sesion:
        corridas = sesion.scalars(sa.select(CorridaOrm)).all()
    assert len(corridas) == 2
    assert all(c.estado == EstadoCorrida.COMPLETADA.value for c in corridas)


def test_el_script_informa_con_claridad_si_ya_hay_una_corrida_activa(tmp_path, motor: MotorPii, capsys) -> None:
    """Revisión adversarial ronda 3, hallazgo 4: el gate de "una corrida a la
    vez" tiene que vivir donde AMBOS procesos (panel y este script) lo vean
    -- confirmado que este script no llamaba `listar_corridas_no_terminales`
    en ningún punto, así que la única protección real que le llega es la que
    la BASE le impone (`ux_corrida_una_activa`, `CorridaEnCursoError`). El
    script tiene que traducir ese rechazo en un mensaje claro y un código de
    salida propio -- no dejar que una excepción cruda le llegue a la
    consola del operador.

    Corrección post CRÍTICO 1: esta prueba simulaba la corrida activa con el
    efecto secundario del propio bug (una corrida de ESTE script que nunca
    se cerraba sola). Ahora que `ejecutar()` cierra sus corridas, eso ya no
    alcanza -- la corrida activa se arma como la dejaría un proceso
    GENUINAMENTE concurrente (el panel, u otra instancia de este mismo
    script todavía en curso): vía `LanzadorCorrida` directo, sin cerrarla,
    ANTES de invocar el script bajo prueba."""
    from anonimizacion.ingesta.lanzador_corrida import LanzadorCorrida
    from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
    from anonimizacion.salida.cuarentena import EscritorCuarentena

    _grupo_completo(tmp_path, "s-gate")
    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    otra_carpeta_en_curso = tmp_path / "otra-corrida-en-curso"
    otra_carpeta_en_curso.mkdir()
    lanzador_de_otro_proceso = LanzadorCorrida(
        repositorio=RepositorioCorridas(engine), cuarentena=EscritorCuarentena(engine)
    )
    lanzador_de_otro_proceso.lanzar(otra_carpeta_en_curso)  # queda activa, deliberadamente sin cerrar

    segundo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert segundo == 2, "codigo de salida propio, distinto de exito (0) y de 'sin PDFs' (1)"
    salida = capsys.readouterr().err
    assert "ya hay una corrida activa" in salida


def test_el_script_despacha_dos_pacientes_distintos_en_grupos_separados(
    tmp_path, motor: MotorPii, monkeypatch: pytest.MonkeyPatch
) -> None:
    """openspec `paralelismo-de-procesamiento` PR 2: el script usa
    `lanzamiento.referencias` como un iterador de GRUPOS (uno por subcarpeta),
    y llama `procesar_grupo` una vez POR GRUPO -- no una sola vez con la
    corrida entera. Con dos pacientes GENUINAMENTE distintos (DNI distinto)
    en subcarpetas separadas, `procesar_grupo` se ejecuta dos veces, cada una
    con su propio lote de 3 documentos, y AMBOS terminan en éxito de forma
    independiente.

    Corrección de revisión adversarial: la versión anterior de este test
    usaba `_grupo_completo` con el DNI hardcodeado (no parametrizado por
    sufijo), así que "dos pacientes" eran en realidad EL MISMO paciente
    (mismo DNI -> mismo HMAC -> mismo `id_paciente`, misma fecha -> mismo
    `id_episodio`). El resultado observado entonces no era un hallazgo de
    producción: era la fixture, no el código, produciendo una colisión de
    identidad. Con DNI genuinamente distintos, el comportamiento correcto es
    6 éxito, 0 cuarentena -- eso es lo que este test verifica ahora.
    """
    (tmp_path / "paciente-1").mkdir()
    (tmp_path / "paciente-2").mkdir()
    _grupo_completo(tmp_path / "paciente-1", "p1", dni="20555888", nombre="Ana Sintetica Uno")
    _grupo_completo(
        tmp_path / "paciente-2",
        "p2",
        dni="20666999",
        nombre="Beatriz Sintetica Dos",
        fecha_nac_lab="10/10/1985",
        fecha_nac_ecg="10-OCT-1985",
    )

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    llamadas: list[int] = []
    original = tareas.procesar_grupo

    def _procesar_grupo_espia(corrida_id, referencias):
        llamadas.append(len(referencias))
        return original(corrida_id, referencias)

    monkeypatch.setattr(modulo.tareas, "procesar_grupo", _procesar_grupo_espia)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 0
    assert sorted(llamadas) == [3, 3], "un grupo por subcarpeta, no un unico lote de 6"

    with Session(engine) as sesion:
        estudios = sesion.scalars(sa.select(Estudio)).all()
        cuarentenas = sesion.scalars(sa.select(Cuarentena)).all()
    assert len(estudios) == 6, "particion exhaustiva: ambos pacientes se publican"
    assert len(cuarentenas) == 0, "dos pacientes genuinamente distintos: ninguno va a cuarentena"


def test_el_script_despacha_el_primer_grupo_antes_de_inventariar_los_siguientes(
    tmp_path, motor: MotorPii, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Centinela de pereza a nivel de script (revisión adversarial, BAJO):
    `LanzadorCorrida.lanzar()` ya tiene su propio test de pereza
    (`test_lanzador_corrida.py`), pero nada garantizaba que
    `scripts/procesar_carpeta.py::ejecutar` preservara esa pereza -- el
    patrón `next()` + `itertools.chain` se puede "simplificar" a
    `list(lanzamiento.referencias)` sin que ningún test existente lo note,
    porque los tests anteriores sólo verifican el RESULTADO final, no CUÁNDO
    se inventaría cada grupo.

    Se espía `tareas.procesar_grupo` para capturar, en el momento exacto del
    PRIMER despacho, cuántos archivos ya se hashearon -- si el script
    materializara todo antes de despachar, ya estarían hasheados los 3
    pacientes; si es perezoso, sólo el primero (más el lookahead mínimo de
    `itertools.groupby`, igual que en `FuenteLocal.listar_grupos`)."""
    from anonimizacion.ingesta.fuente import FuenteLocal

    for indice, sufijo in enumerate(("p1", "p2", "p3")):
        carpeta = tmp_path / f"paciente-{indice}"
        carpeta.mkdir()
        _grupo_completo(carpeta, sufijo, dni=f"2055500{indice}", nombre=f"Paciente Sintetico {indice}")

    original_huella = FuenteLocal._calcular_huella
    llamados: list[str] = []

    def _huella_contada(ruta):
        llamados.append(str(ruta))
        return original_huella(ruta)

    monkeypatch.setattr(FuenteLocal, "_calcular_huella", staticmethod(_huella_contada))

    snapshot_en_primer_despacho: list[int] = []
    original_procesar_grupo = tareas.procesar_grupo

    def _procesar_grupo_espia(corrida_id, referencias):
        if not snapshot_en_primer_despacho:
            snapshot_en_primer_despacho.append(len(llamados))
        return original_procesar_grupo(corrida_id, referencias)

    modulo = _cargar_script()
    monkeypatch.setattr(modulo.tareas, "procesar_grupo", _procesar_grupo_espia)
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 0
    (hasheados_en_primer_despacho,) = snapshot_en_primer_despacho
    assert hasheados_en_primer_despacho < len(llamados), (
        "el script materializo todo el inventario antes de despachar el primer grupo -- "
        "revisa que ejecutar() siga consumiendo lanzamiento.referencias de forma perezosa"
    )


def test_main_usa_construir_engine_postgres_no_create_engine_pelado(monkeypatch) -> None:
    """openspec `paralelismo-de-procesamiento` PR 1: `main()` llamaba
    `sa.create_engine(args.db_url)` pelado, sin `pool_pre_ping` ni
    `pool_recycle` -- ver el docstring de `postgres.py::construir_engine_postgres`
    para el riesgo contra RDS. Wiring de `main()`, no de `ejecutar()`: `ejecutar()`
    ya recibe el `Engine` inyectado y no ejercita esta línea (por eso los tests
    de arriba no la hubieran detectado)."""
    modulo = _cargar_script()
    monkeypatch.setattr("sys.argv", ["procesar_carpeta.py", "--entrada", "carpeta-cualquiera"])
    monkeypatch.setattr(modulo, "obtener_pepper", lambda: b"pepper-wiring-pool-nunca-real")
    monkeypatch.setattr(modulo, "MotorPii", lambda: object())

    llamadas: list[str] = []

    def _engine_espia(url: str) -> sa.Engine:
        llamadas.append(url)
        return sa.create_engine("sqlite:///:memory:")

    monkeypatch.setattr(modulo, "construir_engine_postgres", _engine_espia, raising=False)
    monkeypatch.setattr(modulo, "ejecutar", lambda **kwargs: 0)

    codigo = modulo.main()

    assert codigo == 0
    assert llamadas == [modulo._DB_URL_DEFAULT]


def test_el_apartado_por_sobretamano_antes_de_la_huella_queda_atribuido_a_la_corrida(
    tmp_path, motor: MotorPii
) -> None:
    """Punta a punta desde el script: `FuenteLocal._apartar_por_sobretamano` corre
    ANTES de calcular el sha256, así que ese artefacto nunca puede inventariarse
    ni pasar por `_a_fallo` -- el único otro punto donde el `corrida_id` está en
    mano. Sin `CuarentenaDeCorrida` (justificación en `lanzador_corrida.py`),
    esta fila de cuarentena quedaría con `corrida_id=None`."""
    _grupo_completo(tmp_path, "s2")
    # Los PDFs sintéticos de `_grupo_completo` rondan ~1 KB (texto real vía
    # reportlab/pymupdf): el tope va bien por encima de eso y el "gigante" bien
    # por debajo del default de producción (50 MB) pero muy por encima del tope.
    (tmp_path / "04-gigante.pdf").write_bytes(b"X" * 20_000)

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER, tope_bytes=5_000)

    assert codigo == 0
    with Session(engine) as sesion:
        (corrida,) = sesion.scalars(sa.select(CorridaOrm)).all()
        cuarentenas_por_sobretamano = sesion.scalars(
            sa.select(Cuarentena).where(Cuarentena.codigo == CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO.value)
        ).all()

    assert len(cuarentenas_por_sobretamano) == 1
    assert cuarentenas_por_sobretamano[0].corrida_id == corrida.id_corrida


# --- openspec `paralelismo-de-procesamiento` PR 3: despacho paralelo real --


@pytest.fixture()
def _engine_postgres_real_para_script(monkeypatch: pytest.MonkeyPatch):
    """Motor contra el Postgres real de `docker-compose.yml`, o `skip` si no
    responde -- mismo patrón que `tests/integracion/test_postgres_carrera_real.py`.
    """
    monkeypatch.setattr(socket.socket, "connect", _CONNECT_REAL)
    sonda = sa.create_engine(_URL_POSTGRES_REAL, connect_args={"connect_timeout": 3})
    try:
        with sonda.connect():
            pass
    except Exception as excepcion:  # noqa: BLE001 -- cualquier fallo de conexión es motivo de skip
        pytest.skip(f"Postgres real no disponible en {_URL_POSTGRES_REAL}: {excepcion}")
    finally:
        sonda.dispose()

    engine = construir_engine_postgres(_URL_POSTGRES_REAL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.mark.postgres
def test_el_script_procesa_carpeta_tras_carpeta_sin_bloquearse_contra_postgres_real(
    tmp_path, monkeypatch: pytest.MonkeyPatch, _engine_postgres_real_para_script
) -> None:
    """Reproducción EXACTA del CRÍTICO 1 (revisión adversarial) contra
    Postgres real, con el gate `ux_corrida_una_activa` de verdad (no
    disponible en SQLite antes de esta suite -- acá SÍ es el mismo motor
    real que usa producción): el escenario reportado es el instituto
    corriendo `anonimizacion procesar --entrada <carpeta>` carpeta tras
    carpeta sobre 5 TB. Antes del arreglo, la segunda carpeta fallaba con
    `CorridaEnCursoError` aunque la primera hubiera terminado con éxito
    total -- reproducido dos veces por el equipo de revisión, secuencial y
    con `--procesos 2`."""
    monkeypatch.setenv("ANONIMIZACION_PEPPER", "pepper-test-critico1-postgres-nunca-real")
    engine = _engine_postgres_real_para_script
    carpeta_1 = tmp_path / "carpeta-1"
    carpeta_2 = tmp_path / "carpeta-2"
    carpeta_1.mkdir()
    carpeta_2.mkdir()
    _grupo_completo(carpeta_1, "pg-seg-1", dni="20555888", nombre="Ana Postgres Uno")
    _grupo_completo(
        carpeta_2, "pg-seg-2", dni="20666999", nombre="Beatriz Postgres Dos",
        fecha_nac_lab="10/10/1985", fecha_nac_ecg="10-OCT-1985",
    )

    modulo = _cargar_script()

    primero = modulo.ejecutar(entrada=carpeta_1, engine=engine, motor=None, pepper=PEPPER, procesos=2, db_url=_URL_POSTGRES_REAL)
    segundo = modulo.ejecutar(entrada=carpeta_2, engine=engine, motor=None, pepper=PEPPER, procesos=2, db_url=_URL_POSTGRES_REAL)

    assert primero == 0
    assert segundo == 0, "la segunda carpeta no debe bloquearse por una primera que ya terminó bien"
    with Session(engine) as sesion:
        corridas = sesion.scalars(sa.select(CorridaOrm)).all()
    assert len(corridas) == 2
    assert all(c.estado == EstadoCorrida.COMPLETADA.value for c in corridas)


@pytest.mark.postgres
def test_el_script_despacha_dos_pacientes_en_procesos_reales_distintos_contra_postgres_real(
    tmp_path, monkeypatch: pytest.MonkeyPatch, _engine_postgres_real_para_script
) -> None:
    """Paralelismo REAL, no simulado, por el camino de producción completo:
    `scripts/procesar_carpeta.py::ejecutar(procesos=2, db_url=...)` contra
    Postgres real. Cada proceso hijo (`despacho_paralelo.inicializar_trabajador`,
    instrumentado acá con `directorio_marcador_pid`) deja un archivo nombrado
    con su propio PID -- si el despacho fuera secuencial-disfrazado-de-paralelo,
    solo aparecería UN PID (el del propio proceso de test, si nada se
    despachara a un hijo, o siempre el mismo hijo reusado). Con 2 pacientes en
    subcarpetas separadas y `procesos=2`, tienen que aparecer al menos 2 PIDs
    de sistema operativo genuinamente distintos, y ninguno debe coincidir con
    el PID del proceso de test.

    `ANONIMIZACION_PEPPER` se setea en runtime (no antes de arrancar pytest,
    no vía shell) para confirmar de punta a punta -- no solo en el módulo
    aislado -- que los hijos heredan el pepper del entorno del padre (ver
    `despacho_paralelo.inicializar_trabajador`)."""
    monkeypatch.setenv("ANONIMIZACION_PEPPER", "pepper-test-paralelismo-real-nunca-produccion")

    (tmp_path / "paciente-1").mkdir()
    (tmp_path / "paciente-2").mkdir()
    _grupo_completo(tmp_path / "paciente-1", "par1", dni="20555888", nombre="Ana Sintetica Paralelo Uno")
    _grupo_completo(
        tmp_path / "paciente-2",
        "par2",
        dni="20666999",
        nombre="Beatriz Sintetica Paralelo Dos",
        fecha_nac_lab="10/10/1985",
        fecha_nac_ecg="10-OCT-1985",
    )

    directorio_marcador_pid = tmp_path / "pids"
    directorio_marcador_pid.mkdir()

    modulo = _cargar_script()
    codigo = modulo.ejecutar(
        entrada=tmp_path,
        engine=_engine_postgres_real_para_script,
        motor=None,
        pepper=b"no-se-usa-con-procesos-mayor-a-uno",
        procesos=2,
        db_url=_URL_POSTGRES_REAL,
        directorio_marcador_pid=directorio_marcador_pid,
    )

    assert codigo == 0

    pids_hijos = {archivo.name for archivo in directorio_marcador_pid.iterdir()}
    assert str(os.getpid()) not in pids_hijos, "los grupos deben procesarse en HIJOS, no en el proceso de test"
    assert len(pids_hijos) >= 2, f"se esperaban al menos 2 PIDs de SO distintos, se vieron: {pids_hijos}"

    with Session(_engine_postgres_real_para_script) as sesion:
        estudios = sesion.scalars(sa.select(Estudio)).all()
        cuarentenas = sesion.scalars(sa.select(Cuarentena)).all()
    assert len(estudios) == 6, "particion exhaustiva: ambos pacientes se publican, cada uno en su proceso"
    assert len(cuarentenas) == 0, "dos pacientes genuinamente distintos: ninguno va a cuarentena"


def test_el_script_reporta_metricas_de_recuperacion_si_hubo_recreaciones(capsys, monkeypatch) -> None:
    """ALTO 1 de revisión adversarial (ronda 2): la recuperación ante un
    hijo muerto tiene un costo real en recargas completas del modelo de PII
    (~875 MB medidas cada una) que antes no se veía en ningún lado. Si
    `despachar_en_paralelo` reporta recreaciones/reprocesos vía `metricas`,
    el script tiene que avisarlo por stderr -- rápido, sin Postgres ni
    `ProcessPoolExecutor` real: se reemplaza `despachar_en_paralelo` por un
    doble que solo simula haber mutado `metricas`, igual que haría el real
    tras una recuperación."""
    modulo = _cargar_script()

    def _despachar_en_paralelo_fake(*, grupos, metricas=None, **_kwargs):
        list(grupos)  # consumir, como haria el real
        if metricas is not None:
            metricas.recreaciones_de_pool_principal = 2
            metricas.reprocesos_en_aislamiento = 3
        return [], 0, 0

    monkeypatch.setattr(modulo.despacho_paralelo, "despachar_en_paralelo", _despachar_en_paralelo_fake)

    modulo._despachar_grupos(
        corrida_id="corrida-metricas-script",
        grupos_a_despachar=iter([]),
        procesos=2,
        entrada=Path("."),
        db_url="postgresql+psycopg://usuario:clave@localhost:5433/db",
        tope_bytes=None,
        cuarentena=object(),
        directorio_marcador_pid=None,
    )

    salida = capsys.readouterr().err
    assert "2 recreación" in salida or "2 recreacion" in salida
    assert "3 reproceso" in salida
