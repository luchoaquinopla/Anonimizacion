from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.estados_corrida import EstadoCorrida, EstadoDocumentoCorrida
from anonimizacion.ingesta.repositorio_corridas import RepositorioCorridas
from anonimizacion.salida.modelos_orm import Base, CorridaOrm, Cuarentena, Estudio


def _documento(corrida_id: str) -> DocumentoCorrida:
    return DocumentoCorrida.inventariado(
        corrida_id=corrida_id,
        huella_contenido="a" * 64,
        ruta_autorizada="entrada/estudio.pdf",
    )


def test_repositorio_reanuda_documento_desde_ultimo_estado_persistido() -> None:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-1")
    documento = _documento(corrida.id_corrida)
    documento.avanzar_a(EstadoDocumentoCorrida.CLASIFICADO)

    repositorio.crear_corrida(corrida)
    assert repositorio.registrar_documentos([documento]) == 1
    assert repositorio.registrar_documentos([documento]) == 0

    reanudado = repositorio.documentos_para_reanudar(corrida.id_corrida)

    assert len(reanudado) == 1
    assert reanudado[0].reanudar_desde() is EstadoDocumentoCorrida.CLASIFICADO


def test_repositorio_actualiza_estado_solo_con_version_esperada() -> None:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-1")
    documento = _documento(corrida.id_corrida)
    repositorio.crear_corrida(corrida)
    repositorio.registrar_documentos([documento])
    documento.avanzar_a(EstadoDocumentoCorrida.CLASIFICADO)

    assert repositorio.actualizar_documento(documento, version_esperada=0) is True
    assert repositorio.actualizar_documento(documento, version_esperada=0) is False


def test_repositorio_actualiza_estado_de_corrida_solo_con_version_esperada() -> None:
    """Mismo patrón de bloqueo optimista que `actualizar_documento`, para `Corrida`.

    Sin esto, `CorridaOrm.estado` queda en `creada` para siempre: las
    transiciones que `Corrida.avanzar_a` hace en memoria (`LanzadorCorrida`)
    nunca se persisten -- y el campo `estado` del JSON del embudo termina
    mintiendo durante toda la corrida.
    """
    from anonimizacion.dominio.estados_corrida import EstadoCorrida
    from anonimizacion.salida.modelos_orm import CorridaOrm

    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-1")
    repositorio.crear_corrida(corrida)

    corrida.avanzar_a(EstadoCorrida.INVENTARIANDO)

    assert repositorio.actualizar_corrida(corrida, version_esperada=0) is True
    assert repositorio.actualizar_corrida(corrida, version_esperada=0) is False

    with sa.orm.Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, "corrida-1")
    assert fila.estado == EstadoCorrida.INVENTARIANDO.value
    assert fila.version == 1


# --- registrar_documentos por lote (Decisión 5, design.md) -------------------
#
# Motivo medido: abrir una `Session` y una transacción POR DOCUMENTO -- 100.000
# transacciones sueltas son minutos de arranque para un trabajo que en una
# sesión por millar son segundos. Esta es la versión por lote, con la misma
# guarda de idempotencia por `(corrida_id, huella_contenido)`.


def _documentos(corrida_id: str, cantidad: int) -> list[DocumentoCorrida]:
    return [
        DocumentoCorrida.inventariado(
            corrida_id=corrida_id,
            huella_contenido=f"{indice:0>64}",
            ruta_autorizada=f"entrada/doc-{indice}.pdf",
        )
        for indice in range(cantidad)
    ]


def test_registrar_documentos_inventaria_todos_los_documentos_del_lote() -> None:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-lote")
    repositorio.crear_corrida(corrida)

    assert repositorio.registrar_documentos(_documentos("corrida-lote", 3), tamano_lote=1000) == 3


def test_registrar_documentos_particiona_en_varios_lotes() -> None:
    """Con `tamano_lote` menor a la cantidad total, igual se inventarian todos
    -- una sesión por lote, no una sesión para todo el inventario."""
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-lote")
    repositorio.crear_corrida(corrida)

    total = repositorio.registrar_documentos(_documentos("corrida-lote", 7), tamano_lote=3)

    assert total == 7
    documentos = repositorio.documentos_para_reanudar("corrida-lote")
    assert len(documentos) == 7


def test_listar_corridas_no_terminales_excluye_estados_cerrados() -> None:
    """Feature `despachador-desde-el-panel`: el gate de "una corrida a la
    vez" (`ServicioCorridasReal.crear_corrida`) y la recuperación de arranque
    (`recuperar_corridas_abandonadas`) necesitan poder distinguir corridas
    activas de corridas ya cerradas -- sin esto, cada uno tendría que repetir
    su propio filtro de estados."""
    from anonimizacion.dominio.estados_corrida import EstadoCorrida

    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)

    activa = Corrida.crear("corrida-activa")
    activa.avanzar_a(EstadoCorrida.INVENTARIANDO)
    repositorio.crear_corrida(activa)
    repositorio.actualizar_corrida(activa, version_esperada=0)

    completada = Corrida.crear("corrida-completada")
    repositorio.crear_corrida(completada)
    completada.avanzar_a(EstadoCorrida.INVENTARIANDO)
    repositorio.actualizar_corrida(completada, version_esperada=0)
    completada.avanzar_a(EstadoCorrida.PROCESANDO)
    repositorio.actualizar_corrida(completada, version_esperada=1)
    completada.avanzar_a(EstadoCorrida.COMPLETADA)
    repositorio.actualizar_corrida(completada, version_esperada=2)

    no_terminales = repositorio.listar_corridas_no_terminales()

    assert [c.id_corrida for c in no_terminales] == ["corrida-activa"]
    assert no_terminales[0].estado is EstadoCorrida.INVENTARIANDO
    assert no_terminales[0].version == 1


def test_ultima_actividad_usa_la_evidencia_mas_reciente_entre_corrida_estudio_y_cuarentena() -> None:
    """Revisión adversarial crítico 1 (feature `despachador-desde-el-panel`):
    distinguir una corrida ABANDONADA de una corrida viva en OTRO proceso
    (p. ej. `scripts/procesar_carpeta.py`, que nunca llama
    `marcar_finalizada`/`marcar_fallida`) exige evidencia real de trabajo, no
    sólo el estado administrativo."""
    from anonimizacion.dominio.estados_corrida import EstadoCorrida

    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-evidencia")
    repositorio.crear_corrida(corrida)
    corrida.avanzar_a(EstadoCorrida.INVENTARIANDO)
    repositorio.actualizar_corrida(corrida, version_esperada=0)

    momento_viejo = datetime(2020, 1, 1, tzinfo=timezone.utc)
    momento_reciente = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with sa.orm.Session(motor) as sesion, sesion.begin():
        sesion.add(
            Estudio(
                id_episodio="ep-1",
                tipo_documento="laboratorio",
                fecha_estudio=date(2020, 1, 1),
                precision_hora="ausente",
                clave_documento="clave-evidencia-1",
                corrida_id="corrida-evidencia",
                creado_en=momento_viejo,
            )
        )
        sesion.add(
            Cuarentena(
                id_documento="doc-evidencia-1",
                etapa="ingesta",
                codigo="tipo_no_reconocido",
                corrida_id="corrida-evidencia",
                creado_en=momento_reciente,
            )
        )

    ultima = repositorio.ultima_actividad("corrida-evidencia")

    assert ultima is not None
    # La cuarentena es la evidencia MÁS reciente de las tres candidatas
    # (corrida.actualizada_en de la transición INVENTARIANDO, el estudio
    # viejo y la cuarentena reciente) -- tiene que ganar ella.
    assert ultima.year == 2030


def test_ultima_actividad_de_corrida_inexistente_es_none() -> None:
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)

    assert repositorio.ultima_actividad("no-existe") is None


def test_ultima_actividad_sin_evidencia_de_pipeline_usa_la_transicion_administrativa() -> None:
    """Una corrida recién creada (sin ningún `Estudio`/`Cuarentena` todavía)
    igual tiene evidencia: la última transición de `corrida` misma
    (`actualizada_en`, bump automático de SQLAlchemy en cada `UPDATE`)."""
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-recien-creada")
    repositorio.crear_corrida(corrida)

    ultima = repositorio.ultima_actividad("corrida-recien-creada")

    assert ultima is not None
    assert (datetime.now(timezone.utc).replace(tzinfo=None) - ultima.replace(tzinfo=None)) < timedelta(minutes=1)


def test_registrar_latido_actualiza_ultima_actividad_sin_tocar_estado_ni_version() -> None:
    """Revisión adversarial ronda 3, hallazgo 2: un corpus plano puede tardar
    mucho más que el margen de inactividad SÓLO hasheando -- en toda esa
    ventana no hay ningún `Estudio`/`Cuarentena` que sirva de evidencia. Un
    latido periódico del proceso que trabaja (`_despachar_y_cerrar`) tiene
    que poder refrescar `ultima_actividad` sin depender de que ya se haya
    escrito un documento, y sin pisar `estado`/`version` -- el latido no es
    una transición de dominio, es sólo "sigo vivo"."""
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-con-latido")
    repositorio.crear_corrida(corrida)
    corrida.avanzar_a(EstadoCorrida.INVENTARIANDO)
    repositorio.actualizar_corrida(corrida, version_esperada=0)

    import time

    antes = repositorio.ultima_actividad("corrida-con-latido")
    time.sleep(0.05)  # margen real de reloj: sin esto, un no-op pasaría igual (despues >= antes trivial)
    repositorio.registrar_latido("corrida-con-latido")
    despues = repositorio.ultima_actividad("corrida-con-latido")

    assert despues is not None
    assert antes is not None
    assert despues > antes, "el latido tiene que AVANZAR ultima_actividad, no sólo no retrocederla"
    with sa.orm.Session(motor) as sesion:
        fila = sesion.get(CorridaOrm, "corrida-con-latido")
    assert fila.estado == "inventariando", "el latido no puede cambiar el estado"
    assert fila.version == 1, "el latido no puede pisar la version de bloqueo optimista"


def test_registrar_latido_de_corrida_inexistente_no_rompe() -> None:
    """Best-effort: un latido tardío contra una corrida que ya no existe (o
    que corrió una migración/limpieza entre medio) no debe tumbar el hilo de
    despacho -- sólo no hace nada."""
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)

    repositorio.registrar_latido("no-existe")  # no debe lanzar


def test_registrar_documentos_dos_veces_no_duplica_el_denominador() -> None:
    """6.3: `uq_documento_corrida_huella` evita duplicar el denominador del
    embudo si el mismo inventario se registra dos veces (relanzar la misma
    corrida)."""
    motor = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(motor)
    repositorio = RepositorioCorridas(motor)
    corrida = Corrida.crear("corrida-lote")
    repositorio.crear_corrida(corrida)
    lote = _documentos("corrida-lote", 5)

    primero = repositorio.registrar_documentos(lote, tamano_lote=1000)
    segundo = repositorio.registrar_documentos(lote, tamano_lote=1000)

    assert primero == 5
    assert segundo == 0, "el mismo inventario registrado dos veces no debe duplicar filas"
    assert len(repositorio.documentos_para_reanudar("corrida-lote")) == 5
