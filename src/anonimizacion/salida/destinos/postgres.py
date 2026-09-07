"""Escritor del destino Postgres (tasks.md 7.3, design.md decisión Q1: Postgres como sistema de registro).

`EscritorPostgres` recibe un `sqlalchemy.Engine` ya armado (inyección de
dependencia). Ese `Engine`, contra Postgres real, se arma con
`construir_engine_postgres` (este módulo) -- `scripts/procesar_carpeta.py` y
`scripts/servir_panel.py` lo llaman en vez de `sa.create_engine(args.db_url)`
pelado (openspec `paralelismo-de-procesamiento` PR 1; antes de este cambio sí
llamaban a `sa.create_engine` directo, sin pool contra RDS). En los tests de
este repo, sin Postgres involucrado, se instancia con `sqlite:///:memory:`
(ver `tests/salida/destinos/test_postgres.py` para el porqué eso es válido
acá).

`registrar_vinculo` respalda `ResolutorClaves` (Fase 6) contra la tabla real
`vinculo_paciente`, preservando la MISMA semántica de ambigüedad de
homónimos documentada en `pseudonimizacion/resolutor_claves.py` --
deliberadamente NO usa `INSERT ... ON CONFLICT (id_alt_paciente) DO UPDATE`:
ese patrón pisaría en silencio un puente en conflicto (el bug corregido
post-PR5, commit 07da933; decisión reafirmada en
`openspec/changes/escritura-idempotente/design.md`, Decisión 3). En su lugar
hace SELECT explícito y decide entre INSERT / no-op / marcar ambiguo, calcado
del método `registrar_puente` de `ResolutorClaves`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from anonimizacion.dominio.modelos import RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.salida.modelos_orm import (
    Episodio,
    Estudio,
    MedicionEco,
    MedicionEcg,
    ResultadoLaboratorio,
    TextoSeccionEco,
    VinculoPaciente,
)
from anonimizacion.salida.modelos_salida import ContenidoEcgSalida, ContenidoEcoSalida, ContenidoLaboratorioSalida

# Pivote de la decisión "ancha" para el eco (ver modelos_orm.py::MedicionEco):
# nombre tal como lo imprime el equipo (mayúsculas, normalizado por el
# parser) -> columna fija. Cualquier medida que no matchee acá cae a
# `adicionales` en vez de perderse (ver design.md, "Pendientes": el layout
# real de nombres de medida todavía no está calibrado contra el corpus).
# --- construir_engine_postgres: pool contra RDS ----------------------------
#
# Contra un Postgres local (o SQLite) esto no importa: la conexión vive y
# muere con el proceso de test. Contra RDS en `sa-east-1` sí importa, porque
# tanto RDS como los balanceadores/firewalls intermedios cierran conexiones
# TCP ociosas sin avisarle al cliente -- un proceso de larga vida que reusa
# del pool una conexión ya muerta recibe un error de conexión, y en este
# pipeline eso manda el documento a cuarentena por una falla de
# infraestructura, no por su contenido (falso positivo clínico).
#
# `pool_pre_ping=True`: antes de entregar una conexión del pool, SQLAlchemy
# le hace un "SELECT 1" liviano; si falla, la descarta y abre una nueva en
# vez de propagar el error al llamador. Cuesta un round-trip de red POR
# checkout, no por documento. `EscritorPostgres` abre una `Session` (=~ un
# checkout) por cada `registrar_vinculo`/`escribir_episodio`/`escribir_registro`
# -- hasta 3 por documento en el camino de laboratorio. Con la latencia
# medida para este cambio (54,9 ms mediana a São Paulo) y los 6,67 round
# trips por documento ya medidos (~366 ms de red por documento sin
# pre_ping), 3 checkouts extra sumam ~165 ms más por documento (~45% más
# round trips de red). Es un costo real, no gratis -- se acepta a cambio de
# no perder documentos válidos por una conexión muerta del pool.
#
# `pool_recycle`: Postgres en sí no mata conexiones ociosas por default
# (`idle_session_timeout` viene deshabilitado), pero la red intermedia sí --
# el caso documentado más conocido es el NAT Gateway de AWS, que descarta
# flujos TCP ociosos a los 350 s sin enviar ningún FIN/RST. Este repo no
# documenta la topología de red exacta hacia RDS (VPC/NAT/security groups),
# así que 270 s (4,5 min) es un valor defensivo: reciclar la conexión antes
# de que CUALQUIER middlebox con un timeout de ese orden la mate en
# silencio, no un número derivado de un dato medido de este proyecto. Si
# alguna vez se documenta el timeout real de la red hacia RDS, este valor
# debería ajustarse contra ese dato, no quedar como constante mágica.
#
# `pool_size`: explícito (5, el default histórico de SQLAlchemy) para que el
# presupuesto contra `max_connections` de RDS sea legible más adelante: con
# N procesos (PR 3), el consumo total es N * pool_size + el panel, no un
# número implícito que hay que ir a buscar en la documentación de SQLAlchemy.
#
# SQLite no tiene pool de red: `pool_pre_ping` hace un ping local trivial
# (sin costo real) y `pool_size` lo ignora `SingletonThreadPool` sin error ni
# warning (verificado -- ver `test_construir_engine_postgres_no_rompe_con_sqlite`).
# `pool_recycle` no representa nada porque no hay conexión de red que reciclar.
POOL_RECYCLE_SEGUNDOS = 270
POOL_SIZE = 5


def construir_engine_postgres(url: str) -> Engine:
    """Arma el `Engine` de producción con la config de pool contra RDS.

    Punto único de construcción: `scripts/procesar_carpeta.py` y
    `scripts/servir_panel.py` llaman a esta función en vez de
    `sa.create_engine(url)` pelado -- ver el docstring del módulo para el
    razonamiento completo de cada parámetro.
    """
    return create_engine(url, pool_pre_ping=True, pool_recycle=POOL_RECYCLE_SEGUNDOS, pool_size=POOL_SIZE)


_PIVOTE_MEDIDAS_ECO: dict[str, str] = {
    "AO": "ao",
    "AI": "ai",
    "DDVI": "ddvi",
    "DSVI": "dsvi",
    "FA": "fa",
    "SEPTUM": "septum",
    "P. POSTERIOR": "p_posterior",
    "P.POSTERIOR": "p_posterior",
}


class EscritorPostgres:
    """Escribe `RegistroAnonimizado` y vínculos de paciente contra el esquema de `modelos_orm.py`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # --- vinculo_paciente: respaldo persistente de ResolutorClaves ---------

    def registrar_vinculo(self, id_alt_paciente: str, id_paciente: str) -> None:
        with Session(self._engine) as sesion, sesion.begin():
            existente = sesion.get(VinculoPaciente, id_alt_paciente)

            if existente is None:
                sesion.add(VinculoPaciente(id_alt_paciente=id_alt_paciente, id_paciente=id_paciente, ambiguo=False))
                return

            if existente.ambiguo:
                return  # ya ambiguo -- permanece ambiguo, no hay vuelta atrás

            if existente.id_paciente == id_paciente:
                return  # reprocesamiento idempotente del mismo laboratorio

            # mismo id_alt_paciente, id_paciente distinto -> homónimos reales
            existente.id_paciente = None
            existente.ambiguo = True

    def resolver_vinculo(self, id_alt_paciente: str) -> str | None:
        with Session(self._engine) as sesion:
            fila = sesion.get(VinculoPaciente, id_alt_paciente)
            if fila is None or fila.ambiguo:
                return None
            return fila.id_paciente

    def es_ambiguo(self, id_alt_paciente: str) -> bool:
        with Session(self._engine) as sesion:
            fila = sesion.get(VinculoPaciente, id_alt_paciente)
            return fila is not None and fila.ambiguo

    # --- episodio: determinístico, sin riesgo de ambigüedad -----------------

    def escribir_episodio(self, *, id_episodio: str, id_paciente: str, fecha_ancla: date) -> None:
        """Idempotente: `id_episodio` es una función pura de `(id_paciente, fecha_ancla)`.

        A diferencia de `vinculo_paciente`, acá no hay riesgo de ambigüedad:
        el mismo `id_episodio` siempre corresponde al mismo
        `(id_paciente, fecha_ancla)` (ver `pseudonimizacion/claves.py::
        generar_id_episodio`), así que un insert-si-no-existe es seguro.
        """
        with Session(self._engine) as sesion, sesion.begin():
            if sesion.get(Episodio, id_episodio) is not None:
                return
            sesion.add(Episodio(id_episodio=id_episodio, id_paciente=id_paciente, fecha_ancla=fecha_ancla))

    # --- registro anonimizado: dispatch por tipo_documento -------------------

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        """Inserta el `estudio` del documento y sus mediciones en una sola transaccion.

        La fila de `estudio` y las mediciones que cuelgan de ella se escriben en la
        MISMA sesion a proposito: si el despacho por tipo fallara despues de commitear
        el estudio, quedaria una fila huerfana sin ninguna medicion, indistinguible de
        un documento legitimamente vacio.

        Reprocesar el mismo documento NO duplica. La guarda tiene dos capas, y las
        dos hacen falta: un `SELECT` previo por `clave_documento` evita el trabajo
        en el caso normal, y la restriccion unica de `estudio` es la autoridad
        final ante la carrera que ese `SELECT` no cierra -- dos trabajadores
        pueden consultar antes de que ninguno haya commiteado. El `IntegrityError`
        resultante se trata como "ya escrito", no como fallo: un reprocesamiento
        es un caso normal de operacion.

        Un registro SIN `clave_documento` conserva el comportamiento anterior e
        inserta siempre. No hay garantia posible: la clave se deriva del contenido
        y una fila escrita antes de este cambio no puede recuperarla sin releer el
        documento original.
        """
        if registro.tipo_documento not in (
            TipoDocumento.LABORATORIO,
            TipoDocumento.ECG,
            TipoDocumento.ECOCARDIOGRAMA,
        ):
            raise ValueError(f"tipo_documento no soportado por EscritorPostgres: {registro.tipo_documento!r}")

        with Session(self._engine) as sesion:
            try:
                # La consulta y la insercion van en la MISMA transaccion: separarlas
                # ampliaria la ventana de la carrera sin ganar nada.
                with sesion.begin():
                    if self._existe_documento(sesion, registro.clave_documento):
                        return
                    self._insertar(registro, sesion)
            except IntegrityError:
                # Carrera: otro trabajador inserto la misma `clave_documento` entre
                # nuestra consulta y nuestra insercion. La restriccion unica es la
                # autoridad final; el documento ya esta escrito y no hay nada que
                # hacer. `sesion.begin()` ya revirtio al propagar la excepcion.
                pass

    @staticmethod
    def _existe_documento(sesion: Session, clave_documento: str | None) -> bool:
        if clave_documento is None:
            return False
        return (
            sesion.scalar(
                select(Estudio.id_estudio).where(Estudio.clave_documento == clave_documento)
            )
            is not None
        )

    def _insertar(self, registro: RegistroAnonimizado, sesion: Session) -> None:
        # `corrida_id` viaja tal cual desde `RegistroAnonimizado` (spec
        # `trazabilidad-por-corrida`, design.md "Recorrido"): sin esto, ningún
        # llamador -- ni `procesar_grupo`, ni `scripts/procesar_carpeta.py` --
        # puede hacer que `corrida_id` llegue de punta a punta hasta `estudio`,
        # sin importar qué tan bien propague el pipeline el parámetro.
        # `creado_en` no se pasa acá: el default de Python de la columna
        # (`_ahora_utc`, `modelos_orm.py`) ya lo estampa al insertar.
        estudio = Estudio(
            id_episodio=registro.id_episodio,
            tipo_documento=registro.tipo_documento.value,
            fecha_estudio=registro.fecha_estudio,
            hora_estudio=registro.hora_estudio,
            precision_hora=registro.precision_hora.value,
            clave_documento=registro.clave_documento,
            corrida_id=registro.corrida_id,
        )
        sesion.add(estudio)
        sesion.flush()  # asigna id_estudio sin cerrar la transaccion
        id_estudio = estudio.id_estudio

        if registro.tipo_documento is TipoDocumento.LABORATORIO:
            self._escribir_laboratorio(registro, sesion, id_estudio)
        elif registro.tipo_documento is TipoDocumento.ECG:
            self._escribir_ecg(registro, sesion, id_estudio)
        else:
            self._escribir_eco(registro, sesion, id_estudio)

    def _escribir_laboratorio(
        self, registro: RegistroAnonimizado, sesion: Session, id_estudio: int
    ) -> None:
        contenido: ContenidoLaboratorioSalida = registro.contenido
        for fila in contenido.resultados:
            sesion.add(
                ResultadoLaboratorio(
                    id_episodio=registro.id_episodio,
                    id_estudio=id_estudio,
                    id_medico=contenido.id_medico,
                    analito=fila.analito,
                    seccion=fila.seccion,
                    valor_num=fila.valor_num,
                    valor_texto=fila.valor_texto,
                    unidad=fila.unidad,
                    ref_min=fila.ref_min,
                    ref_max=fila.ref_max,
                )
            )

    def _escribir_ecg(self, registro: RegistroAnonimizado, sesion: Session, id_estudio: int) -> None:
        contenido: ContenidoEcgSalida = registro.contenido
        sesion.add(
            MedicionEcg(
                id_episodio=registro.id_episodio,
                id_estudio=id_estudio,
                id_medico=contenido.id_medico,
                vent_rate=contenido.vent_rate,
                pr_interval=contenido.pr_interval,
                qrs_duration=contenido.qrs_duration,
                qt_qtc=contenido.qt_qtc,
                ejes=contenido.ejes,
                adicionales=dict(registro.adicionales) or None,
            )
        )

    def _escribir_eco(self, registro: RegistroAnonimizado, sesion: Session, id_estudio: int) -> None:
        contenido: ContenidoEcoSalida = registro.contenido

        columnas_ancha: dict[str, str] = {}
        unidades: dict[str, str] = {}
        extras: dict[str, str] = {}
        for medida in contenido.medidas:
            columna = _PIVOTE_MEDIDAS_ECO.get(medida.nombre.strip().upper())
            if columna is None:
                extras[medida.nombre] = medida.valor
                continue
            columnas_ancha[columna] = medida.valor
            if medida.unidad:
                unidades[columna] = medida.unidad

        sesion.add(
            MedicionEco(
                id_episodio=registro.id_episodio,
                id_estudio=id_estudio,
                id_medico_solicitante=contenido.id_medico_solicitante,
                id_medico_informante=contenido.id_medico_informante,
                id_matricula_informante=contenido.id_matricula_informante,
                unidades=unidades or None,
                adicionales=extras or None,
                **columnas_ancha,
            )
        )
        for seccion in contenido.secciones_texto:
            sesion.add(
                TextoSeccionEco(
                    id_episodio=registro.id_episodio, seccion=seccion.nombre, texto=seccion.texto
                )
            )
