"""Escritor del destino Postgres. `EscritorPostgres` recibe un `Engine` inyectado, armado por
`construir_engine_postgres` contra RDS real o `sqlite:///:memory:` en tests. `registrar_vinculo`
preserva la semántica de ambigüedad de `ResolutorClaves` sin `ON CONFLICT DO UPDATE` (pisaría
un puente en conflicto en silencio), tolerando la carrera de procesos concurrentes."""

from __future__ import annotations

from datetime import date
from typing import Callable

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from anonimizacion.dominio.modelos import RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.salida.codec_senal import VERSION_FORMATO_ACTUAL, codificar_mascara, codificar_muestras
from anonimizacion.salida.modelos_orm import (
    Episodio,
    Estudio,
    MedicionEco,
    MedicionEcg,
    ResultadoLaboratorio,
    SenalEcgOrm,
    TextoSeccionEco,
    VinculoPaciente,
)
from anonimizacion.salida.modelos_salida import ContenidoEcgSalida, ContenidoEcoSalida, ContenidoLaboratorioSalida

# Cualquier medida que no matchee cae a `adicionales` en vez de perderse (layout no calibrado contra corpus real).
# --- construir_engine_postgres: pool contra RDS ----------------------------
# pool_pre_ping evita reusar una conexión muerta del pool (RDS/firewalls cierran TCP ocioso sin
# avisar); sin esto, el documento cae en cuarentena por una falla de infraestructura, no de contenido.
# Costo medido: ~366 ms de red por documento SIN pre_ping (6,67 round trips, 54,9 ms mediana São
# Paulo); pre_ping AGREGA ~124 ms (~2,25 checkouts extra) en el caso típico, hasta ~220 ms bajo
# contención (4 checkouts). Costo real, aceptado para no perder documentos válidos.
# Invariante: «Conexión a la base, verificación y tope de espera» (Obsidian, Invariantes medidos).
# pool_recycle recicla por EDAD desde el checkout, no detecta inactividad -- pool_pre_ping es la
# defensa real contra conexión muerta por inactividad; pool_recycle es complemento, no sustituto.
POOL_RECYCLE_SEGUNDOS = 270
# Explícito para que el presupuesto contra max_connections de RDS sea legible (N procesos * pool_size).
POOL_SIZE = 5

# Tope de conexión inicial: sin esto, psycopg cuelga varios minutos en el handshake contra un host
# que no responde. pool_pre_ping protege una conexión que ya estaba viva; esto protege el primer intento.
CONNECT_TIMEOUT_SEGUNDOS = 5


def construir_engine_postgres(url: str) -> Engine:
    """Arma el `Engine` de producción con la config de pool contra RDS. `connect_args` sólo se
    agrega para `postgresql`: SQLite no entiende esa palabra clave (usa `timeout`)."""
    kwargs: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_recycle": POOL_RECYCLE_SEGUNDOS,
        "pool_size": POOL_SIZE,
    }
    if make_url(url).get_backend_name() == "postgresql":
        kwargs["connect_args"] = {"connect_timeout": CONNECT_TIMEOUT_SEGUNDOS}
    return create_engine(url, **kwargs)


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
        # Whitelist y despacho son la misma estructura: no hay dos listas que puedan desincronizarse.
        self._escritores_por_tipo: dict[
            TipoDocumento, Callable[[RegistroAnonimizado, Session, int], None]
        ] = {
            TipoDocumento.LABORATORIO: self._escribir_laboratorio,
            TipoDocumento.ECG: self._escribir_ecg,
            TipoDocumento.ECOCARDIOGRAMA: self._escribir_eco,
        }

    # --- vinculo_paciente: respaldo persistente de ResolutorClaves ---------

    def registrar_vinculo(self, id_alt_paciente: str, id_paciente: str) -> None:
        """Inserta o decide sobre `vinculo_paciente`, tolerando la carrera de N procesos: a
        diferencia de `escribir_registro`, el `IntegrityError` no se descarta -- se relee el
        estado real y se aplica la misma decisión, porque "ya existe" puede ser un homónimo."""
        with Session(self._engine) as sesion:
            try:
                with sesion.begin():
                    existente = self._buscar_vinculo(sesion, id_alt_paciente)
                    if existente is not None:
                        self._decidir_vinculo(existente, id_paciente)
                        return
                    sesion.add(
                        VinculoPaciente(id_alt_paciente=id_alt_paciente, id_paciente=id_paciente, ambiguo=False)
                    )
            except IntegrityError:
                pass
            else:
                return

        # Carrera: se resuelve en una sesión nueva, releyendo el estado real en vez de asumir "ya existe" = "nada que hacer".
        with Session(self._engine) as sesion, sesion.begin():
            existente = sesion.get(VinculoPaciente, id_alt_paciente)
            if existente is None:
                # Defensivo: no debería pasar, este pipeline no borra vinculo_paciente.
                sesion.add(
                    VinculoPaciente(id_alt_paciente=id_alt_paciente, id_paciente=id_paciente, ambiguo=False)
                )
                return
            self._decidir_vinculo(existente, id_paciente)

    @staticmethod
    def _buscar_vinculo(sesion: Session, id_alt_paciente: str) -> VinculoPaciente | None:
        return sesion.get(VinculoPaciente, id_alt_paciente)

    @staticmethod
    def _decidir_vinculo(existente: VinculoPaciente, id_paciente: str) -> None:
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
        """Idempotente: `id_episodio` es función pura de `(id_paciente, fecha_ancla)`, sin
        riesgo de ambigüedad -- a diferencia de `registrar_vinculo`, tratar `IntegrityError`
        como "ya escrito" alcanza."""
        with Session(self._engine) as sesion:
            try:
                with sesion.begin():
                    if self._buscar_episodio(sesion, id_episodio) is not None:
                        return
                    sesion.add(Episodio(id_episodio=id_episodio, id_paciente=id_paciente, fecha_ancla=fecha_ancla))
            except IntegrityError:
                # Carrera: función pura, la fila que ganó es idéntica a la que hubiéramos escrito.
                pass

    @staticmethod
    def _buscar_episodio(sesion: Session, id_episodio: str) -> Episodio | None:
        return sesion.get(Episodio, id_episodio)

    # --- registro anonimizado: dispatch por tipo_documento -------------------

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        """Inserta el `estudio` y sus mediciones en una sola transacción (evita una fila
        huérfana si el despacho por tipo falla después de commitear). Reprocesar no duplica:
        guarda de dos capas (SELECT + restricción única), `IntegrityError` se trata como "ya escrito"."""
        if registro.tipo_documento not in self._escritores_por_tipo:
            raise ValueError(f"tipo_documento no soportado por EscritorPostgres: {registro.tipo_documento!r}")

        with Session(self._engine) as sesion:
            try:
                # Consulta e inserción en la misma transacción: separarlas ampliaría la carrera sin ganar nada.
                with sesion.begin():
                    if self._existe_documento(sesion, registro.clave_documento):
                        return
                    self._insertar(registro, sesion)
            except IntegrityError:
                # Carrera resuelta por la restricción única: el documento ya está escrito.
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
        estudio = Estudio(
            id_episodio=registro.id_episodio,
            tipo_documento=registro.tipo_documento.value,
            fecha_estudio=registro.fecha_estudio,
            hora_estudio=registro.hora_estudio,
            precision_hora=registro.precision_hora.value,
            clave_documento=registro.clave_documento,
            corrida_id=registro.corrida_id,
            completo=registro.completo,
            campos_no_extraidos=list(registro.campos_no_extraidos),
            # Ya viene saneado de PII de médico/técnico; se persiste para los 3 tipos de documento.
            adicionales=dict(registro.adicionales) or None,
        )
        sesion.add(estudio)
        sesion.flush()  # asigna id_estudio sin cerrar la transacción
        id_estudio = estudio.id_estudio

        # Mismo diccionario que la whitelist de escribir_registro; KeyError si se bypasea esa guarda.
        self._escritores_por_tipo[registro.tipo_documento](registro, sesion, id_estudio)

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
            )
        )
        # Misma transacción que estudio, para no dejar una fila huérfana sin señal. None cuando el layout no validó: ya quedó en campos_no_extraidos.
        if contenido.senal is not None:
            sesion.add(
                SenalEcgOrm(
                    id_estudio=id_estudio,
                    muestras_uv=codificar_muestras(contenido.senal.muestras_uv),
                    mascara=codificar_mascara(contenido.senal.mascara),
                    frecuencia_hz=contenido.senal.frecuencia_hz,
                    version_extractor=contenido.senal.version_extractor,
                    version_formato=VERSION_FORMATO_ACTUAL,
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
                # Medidas del cuerpo sin pivote, distinto de estudio.adicionales (campos del header).
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
