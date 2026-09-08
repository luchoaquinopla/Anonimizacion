"""Repositorio SQL para recuperar corridas y documentos luego de una interrupción.

Producción hoy sólo llama `registrar_documentos` (vía `LanzadorCorrida.lanzar`)
y `obtener_corrida`/`actualizar_corrida` (marcar `PROCESANDO`, ver
`servicio_corridas.py`). `documentos_para_reanudar` y `actualizar_documento`
no tienen llamador de producción todavía -- son la mitad de la reanudación
que falta conectar. Ver `dominio/estados_corrida.py` para el detalle completo
de qué existe, qué falta y qué decisión lo desbloquea.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.estados_corrida import EstadoCorrida, EstadoDocumentoCorrida
from anonimizacion.salida.modelos_orm import CorridaOrm, Cuarentena, DocumentoCorridaOrm, Estudio

_ESTADOS_TERMINALES = {
    EstadoDocumentoCorrida.APROBADO,
    EstadoDocumentoCorrida.CUARENTENA,
    EstadoDocumentoCorrida.ERROR_FINAL,
}

# Estados TERMINALES de `corrida` (plano de control, no de documento -- ver
# `_ESTADOS_TERMINALES` arriba para la distinción). Usado por
# `listar_corridas_no_terminales`: feature `despachador-desde-el-panel`, para
# el gate de "una corrida a la vez" y la recuperación de arranque.
_ESTADOS_CORRIDA_TERMINALES = {
    EstadoCorrida.COMPLETADA,
    EstadoCorrida.COMPLETADA_CON_CUARENTENA,
    EstadoCorrida.FALLIDA,
}


def _es_activa(estado: EstadoCorrida) -> bool:
    """`CorridaOrm.activa` -- ver su docstring en `modelos_orm.py` para el
    porqué (revisión adversarial ronda 3, hallazgo 4: el gate de "una
    corrida a la vez" tiene que vivir en la BASE, no sólo en un lock de un
    proceso, para que `scripts/procesar_carpeta.py` (otro proceso) también
    lo respete)."""
    return estado not in _ESTADOS_CORRIDA_TERMINALES


class RepositorioCorridas:
    """Persiste la unidad administrativa y permite reanudar documentos no terminales."""

    def __init__(self, motor: Engine) -> None:
        self._motor = motor

    def crear_corrida(self, corrida: Corrida) -> None:
        """Inserta la fila -- o deja que la BASE la rechace si ya hay otra
        corrida activa (`ux_corrida_una_activa`, revisión adversarial ronda
        3): `IntegrityError` se propaga sin atrapar acá, `LanzadorCorrida.lanzar`
        es quien la traduce a `CorridaEnCursoError`, porque es quien tiene
        acceso a `listar_corridas_no_terminales` para armar un mensaje útil."""
        with Session(self._motor) as sesion, sesion.begin():
            if sesion.get(CorridaOrm, corrida.id_corrida) is None:
                sesion.add(
                    CorridaOrm(
                        id_corrida=corrida.id_corrida,
                        estado=corrida.estado.value,
                        version=corrida.version,
                        activa=_es_activa(corrida.estado),
                        ruta_autorizada=corrida.ruta_autorizada,
                    )
                )

    def obtener_corrida(self, id_corrida: str) -> Corrida | None:
        """Recupera `Corrida` (estado + version) para volver a avanzarla.

        Necesario para `LanzadorCorrida.marcar_procesando` (cierre de silencio
        de auditoría, `fix/silencios-de-ingesta-y-panel`): quien marca
        `PROCESANDO` no necesariamente es el mismo proceso/objeto que corrió
        `lanzar()`, así que no puede asumir que tiene el `Corrida` en memoria
        -- tiene que leerlo.
        """
        with Session(self._motor) as sesion:
            fila = sesion.get(CorridaOrm, id_corrida)
        if fila is None:
            return None
        return Corrida(
            id_corrida=fila.id_corrida,
            estado=EstadoCorrida(fila.estado),
            version=fila.version,
            ruta_autorizada=fila.ruta_autorizada,
        )

    def listar_corridas_no_terminales(self) -> list[Corrida]:
        """Corridas en cualquier estado ACTIVO (no `COMPLETADA`/
        `COMPLETADA_CON_CUARENTENA`/`FALLIDA`) -- feature `despachador-desde-el-panel`.

        Dos llamadores reales, misma pregunta: "¿hay trabajo en curso?"

        - `ServicioCorridasReal.crear_corrida`: gate de "una corrida a la
          vez" -- rechaza un `POST /corridas` nuevo mientras una siga activa
          (ver su docstring para el porqué de esa decisión, memoria y
          `ProcessPoolExecutor` compartidos entre corridas concurrentes).
        - `lanzador_corrida.recuperar_corridas_abandonadas`: al arrancar el
          servidor, cualquier corrida que esta consulta devuelva es
          necesariamente una corrida abandonada por un proceso anterior (el
          servidor es de un solo proceso, sin persistencia de "hay un hilo
          corriendo para este `corrida_id`").

        Orden estable por `id_corrida` (no hay columna de fecha de creación
        en `corrida` hoy) -- sólo importa para que el gate reporte SIEMPRE la
        misma corrida activa en `409`, no una elección arbitraria entre
        varias filas no terminales.
        """
        with Session(self._motor) as sesion:
            filas = sesion.scalars(
                select(CorridaOrm)
                .where(CorridaOrm.estado.not_in({e.value for e in _ESTADOS_CORRIDA_TERMINALES}))
                .order_by(CorridaOrm.id_corrida)
            ).all()
        return [
            Corrida(id_corrida=fila.id_corrida, estado=EstadoCorrida(fila.estado), version=fila.version)
            for fila in filas
        ]

    def ultima_actividad(self, id_corrida: str) -> datetime | None:
        """Última evidencia REAL de trabajo en curso sobre `id_corrida`, sin
        importar QUÉ proceso la produjo -- revisión adversarial crítico 1
        (feature `despachador-desde-el-panel`).

        `recuperar_corridas_abandonadas` asumía "servidor de un solo proceso
        ⇒ toda corrida no terminal está abandonada". Es falso:
        `scripts/procesar_carpeta.py` usa el MISMO `LanzadorCorrida` contra
        la MISMA base, en OTRO proceso, y nunca llama
        `marcar_finalizada`/`marcar_fallida` -- dejar una corrida en
        `PROCESANDO` mientras escribe documentos reales es su comportamiento
        NORMAL, no un bug. Reproducido contra Postgres real: arrancar el
        panel mientras el script seguía corriendo la marcaba `FALLIDA` a
        mitad de la escritura -- la inversión exacta del defecto que cerró
        el PR #33.

        El máximo entre tres candidatos, cualquiera puede ganar:
        - `corrida.actualizada_en`: se actualiza sola (`onupdate`, columna de
          SQLAlchemy) en cada transición de estado -- cubre una corrida
          recién creada, antes de que exista ningún documento publicado.
        - El `creado_en` más reciente de `estudio` para esta corrida:
          evidencia de que el pipeline sigue publicando.
        - El `creado_en` más reciente de `cuarentena` para esta corrida:
          evidencia de que el pipeline sigue procesando, aunque el último
          documento haya terminado en cuarentena.

        `None` sólo si la corrida no existe -- el llamador decide qué hacer
        con eso (`recuperar_corridas_abandonadas` sólo llama esto sobre
        corridas que `listar_corridas_no_terminales` ya confirmó que existen).

        LIMITACIÓN CONOCIDA, ACEPTADA, NO RESUELTA ACÁ: `documento_corrida`
        (el inventario) no tiene columna de tiempo -- una corrida que tarda
        mucho SÓLO inventariando (antes de que `procesar_grupo` escriba el
        primer `estudio`/`cuarentena`) no deja evidencia nueva más allá de la
        transición a `INVENTARIANDO`. El margen de inactividad
        (`recuperar_corridas_abandonadas`) tiene que ser generoso para no
        confundir ese tramo con abandono.
        """
        with Session(self._motor) as sesion:
            fila = sesion.get(CorridaOrm, id_corrida)
            if fila is None:
                return None
            ultimo_estudio = sesion.scalar(
                select(func.max(Estudio.creado_en)).where(Estudio.corrida_id == id_corrida)
            )
            ultima_cuarentena = sesion.scalar(
                select(func.max(Cuarentena.creado_en)).where(Cuarentena.corrida_id == id_corrida)
            )
        candidatos = [fila.actualizada_en, ultimo_estudio, ultima_cuarentena]
        return max(momento for momento in candidatos if momento is not None)

    def registrar_latido(self, id_corrida: str) -> None:
        """Toca `corrida.actualizada_en` SIN pasar por `Corrida.avanzar_a` --
        no es una transición de dominio, es sólo "el proceso que trabaja
        sigue vivo" (revisión adversarial ronda 3, hallazgo 2).

        Por qué hace falta además de `ultima_actividad`: un corpus PLANO (sin
        subcarpetas) colapsa en un único grupo, y `FuenteLocal.listar_grupos`
        agota TODO el listado -- hasheando cada archivo -- antes de entregar
        ese grupo (`ingesta/fuente.py`, docstring de `listar_grupos`). Con
        ~400.000 documentos eso puede tardar mucho más que cualquier margen
        de inactividad razonable, y en toda esa ventana no se escribe ningún
        `estudio` ni `cuarentena` -- la única evidencia sería la transición a
        `PROCESANDO`, marcada una sola vez al principio. Sin un latido
        propio, esa ventana larga y silenciosa es indistinguible de una
        corrida abandonada.

        Llamador de producción: un hilo de latido dedicado, lanzado por
        `web/servicio_corridas.py::_despachar_y_cerrar` mientras el despacho
        real está en curso -- ver ese módulo para el intervalo.

        Sin bloqueo optimista (a propósito): un latido es best-effort y
        NUNCA debe competir por la versión de dominio con
        `marcar_procesando`/`marcar_finalizada`/`marcar_fallida` -- si pisa
        una actualización real por una carrera rarísima, la próxima vuelta
        del latido (segundos después) lo corrige solo. `estado`/`version` NO
        se tocan: sólo `actualizada_en`.

        Silencioso si `id_corrida` no existe (corrida borrada/migrada entre
        medio): un latido tardío no puede tumbar el hilo de despacho por una
        fila que ya no está.
        """
        with Session(self._motor) as sesion, sesion.begin():
            sesion.execute(
                update(CorridaOrm)
                .where(CorridaOrm.id_corrida == id_corrida)
                .values(actualizada_en=datetime.now(timezone.utc))
            )

    def registrar_documentos(self, documentos: Sequence[DocumentoCorrida], *, tamano_lote: int = 1000) -> int:
        """Inventaría `documentos` en lotes -- una sesión por lote, no una por documento.

        Motivo medido (design.md, Decisión 5): abrir una `Session` y una
        transacción por documento sale caro -- 100.000 transacciones sueltas
        son minutos de arranque para un trabajo que en una sesión por millar
        son segundos. Esta es la versión por lote, con la misma guarda de
        idempotencia por `(corrida_id, huella_contenido)` que
        `uq_documento_corrida_huella` ya exige: consulta las huellas
        existentes del lote antes de insertar, así que relanzar la misma
        corrida (mismo inventario, mismas huellas) no duplica el denominador
        del embudo.

        Devuelve la cantidad de filas efectivamente insertadas.
        """
        insertados = 0
        for inicio in range(0, len(documentos), tamano_lote):
            lote = documentos[inicio : inicio + tamano_lote]
            if not lote:
                continue
            with Session(self._motor) as sesion, sesion.begin():
                existentes = set(
                    sesion.execute(
                        select(DocumentoCorridaOrm.corrida_id, DocumentoCorridaOrm.huella_contenido).where(
                            DocumentoCorridaOrm.corrida_id.in_({d.corrida_id for d in lote}),
                            DocumentoCorridaOrm.huella_contenido.in_({d.huella_contenido for d in lote}),
                        )
                    ).all()
                )
                for documento in lote:
                    if (documento.corrida_id, documento.huella_contenido) in existentes:
                        continue
                    sesion.add(
                        DocumentoCorridaOrm(
                            corrida_id=documento.corrida_id,
                            huella_contenido=documento.huella_contenido,
                            ruta_autorizada=documento.ruta_autorizada,
                            estado=documento.estado.value,
                            version=documento.version,
                        )
                    )
                    insertados += 1
        return insertados

    def documentos_para_reanudar(self, id_corrida: str) -> list[DocumentoCorrida]:
        with Session(self._motor) as sesion:
            filas = sesion.scalars(
                select(DocumentoCorridaOrm)
                .where(DocumentoCorridaOrm.corrida_id == id_corrida)
                .order_by(DocumentoCorridaOrm.id)
            ).all()
        return [
            self._a_documento(fila)
            for fila in filas
            if EstadoDocumentoCorrida(fila.estado) not in _ESTADOS_TERMINALES
        ]

    def actualizar_documento(self, documento: DocumentoCorrida, *, version_esperada: int) -> bool:
        """Confirma un estado sólo si ningún worker lo modificó desde la versión esperada."""
        with Session(self._motor) as sesion, sesion.begin():
            resultado = sesion.execute(
                update(DocumentoCorridaOrm)
                .where(
                    DocumentoCorridaOrm.corrida_id == documento.corrida_id,
                    DocumentoCorridaOrm.huella_contenido == documento.huella_contenido,
                    DocumentoCorridaOrm.version == version_esperada,
                )
                .values(estado=documento.estado.value, version=documento.version)
            )
            return resultado.rowcount == 1

    def actualizar_corrida(self, corrida: Corrida, *, version_esperada: int) -> bool:
        """Persiste `corrida.estado`, mismo bloqueo optimista que `actualizar_documento`.

        Sin esto, las transiciones `CREADA -> INVENTARIANDO -> PROCESANDO` que
        `Corrida.avanzar_a` hace en memoria (`LanzadorCorrida`, design.md
        "Recorrido") nunca llegan a `corrida.estado` -- la fila queda en
        `creada` para siempre, y ese es un campo que después el embudo expone
        tal cual (`ServicioCorridasReal`, design.md "El contrato JSON").
        Persistir sólo estas tres transiciones -- nada de cierre en estados
        terminales -- es justo lo que design.md pide: "el panel deriva la
        marcha de la evidencia, no del estado" (Decisión 8); esto es
        trazabilidad administrativa, no un sustituto de esa decisión.
        """
        with Session(self._motor) as sesion, sesion.begin():
            resultado = sesion.execute(
                update(CorridaOrm)
                .where(
                    CorridaOrm.id_corrida == corrida.id_corrida,
                    CorridaOrm.version == version_esperada,
                )
                .values(estado=corrida.estado.value, version=corrida.version, activa=_es_activa(corrida.estado))
            )
            return resultado.rowcount == 1

    @staticmethod
    def _a_documento(fila: DocumentoCorridaOrm) -> DocumentoCorrida:
        return DocumentoCorrida(
            corrida_id=fila.corrida_id,
            huella_contenido=fila.huella_contenido,
            ruta_autorizada=fila.ruta_autorizada,
            estado=EstadoDocumentoCorrida(fila.estado),
            version=fila.version,
        )
