"""Modelos SQLAlchemy del esquema de salida: laboratorio EAV (analitos variables), ECG/eco
anchos (medidas fijas), episodio/corrida/documento_corrida para estado durable, cuarentena
sólo con metadata sin PII. `adicionales`/`unidades` usan JSON con variante JSONB en Postgres,
nunca como camino de queries (sin índice ni WHERE)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Time, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

_LONGITUD_CLAVE_HEX = 32  # 16 bytes HMAC truncados, codificados en hex (ver pseudonimizacion/claves.py)

_JsonPortable = JSON().with_variant(JSONB(), "postgresql")


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarativa común a todas las tablas de `salida`."""


class VinculoPaciente(Base):
    """Respaldo persistente de `ResolutorClaves` (puente `id_alt_paciente -> id_paciente`).
    `id_paciente` queda en `NULL` cuando `ambiguo=True`: no hay candidato seguro."""

    __tablename__ = "vinculo_paciente"

    id_alt_paciente: Mapped[str] = mapped_column(String(_LONGITUD_CLAVE_HEX), primary_key=True)
    id_paciente: Mapped[str | None] = mapped_column(String(_LONGITUD_CLAVE_HEX), nullable=True)
    ambiguo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Episodio(Base):
    """Un episodio clínico: `id_paciente` + ventana ±7 días con ancla en `fecha_ancla`."""

    __tablename__ = "episodio"

    id_episodio: Mapped[str] = mapped_column(String(_LONGITUD_CLAVE_HEX), primary_key=True)
    id_paciente: Mapped[str] = mapped_column(String(_LONGITUD_CLAVE_HEX), index=True, nullable=False)
    fecha_ancla: Mapped[date] = mapped_column(Date, nullable=False)


class Estudio(Base):
    """Un documento clínico publicado, con su propia fecha (distinta de `episodio.fecha_ancla`,
    la del grupo). `precision_hora` no es derivable de `hora_estudio`: `NULL` con
    `precision_hora='ausente'` significa "no la trae", nunca medianoche por defecto."""

    __tablename__ = "estudio"
    __table_args__ = (
        UniqueConstraint("clave_documento", name="uq_estudio_clave_documento"),
        Index("ix_estudio_corrida_creado", "corrida_id", "creado_en"),
    )

    id_estudio: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_episodio: Mapped[str] = mapped_column(
        String(_LONGITUD_CLAVE_HEX), ForeignKey("episodio.id_episodio"), index=True, nullable=False
    )
    tipo_documento: Mapped[str] = mapped_column(String, nullable=False)
    fecha_estudio: Mapped[date] = mapped_column(Date, nullable=False)
    hora_estudio: Mapped[time | None] = mapped_column(Time, nullable=True)
    precision_hora: Mapped[str] = mapped_column(String, nullable=False)
    #: HMAC del sha256 (identidad estable del documento); NULL en filas preexistentes sin backfill.
    clave_documento: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Sin FK hacia `corrida` a propósito: `corrida` es plano de control, ésta es plano de datos.
    corrida_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: NULL en filas preexistentes: no se sabe cuándo se escribieron, y datarlas con la migración sería mentira.
    creado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=True)
    #: NULL = no se sabe si estaba completa (filas preexistentes); las nuevas siempre la completan.
    completo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: id_campo que el PDF traía y el parser no citó, nunca texto libre; puede repetirse por instancia faltante.
    campos_no_extraidos: Mapped[list[str] | None] = mapped_column(_JsonPortable, nullable=True)
    #: Campos de HEADER sin columna propia (edad, sexo, peso...), ya sin PII de médico/técnico; distinto de medicion_eco.adicionales (cuerpo del eco).
    adicionales: Mapped[dict | None] = mapped_column(_JsonPortable, nullable=True)


class MedicionEcg(Base):
    """Medidas de ECG -- ancha, esquema fijo (ver `ContenidoEcg`)."""

    __tablename__ = "medicion_ecg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_episodio: Mapped[str] = mapped_column(
        String(_LONGITUD_CLAVE_HEX), ForeignKey("episodio.id_episodio"), index=True, nullable=False
    )
    id_estudio: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("estudio.id_estudio"), index=True, nullable=True
    )
    id_medico: Mapped[str | None] = mapped_column(String(_LONGITUD_CLAVE_HEX), nullable=True)
    vent_rate: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_interval: Mapped[str | None] = mapped_column(String, nullable=True)
    qrs_duration: Mapped[str | None] = mapped_column(String, nullable=True)
    qt_qtc: Mapped[str | None] = mapped_column(String, nullable=True)
    ejes: Mapped[str | None] = mapped_column(String, nullable=True)


class SenalEcgOrm(Base):
    """Señal de ECG calibrada, codificada (`codec_senal.py`). PK = FK contra `estudio`, 1:1
    estricto con `ON DELETE CASCADE`. `muestras_uv`/`mascara` ya llegan comprimidas, por eso `LargeBinary`."""

    __tablename__ = "senal_ecg"

    id_estudio: Mapped[int] = mapped_column(
        Integer, ForeignKey("estudio.id_estudio", ondelete="CASCADE"), primary_key=True
    )
    muestras_uv: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mascara: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    frecuencia_hz: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    version_extractor: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Versión del esquema binario de codec_senal.py, distinta de version_extractor (algoritmo).
    version_formato: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ResultadoLaboratorio(Base):
    """Una fila EAV por resultado de laboratorio: `(id_episodio, analito, seccion, ...)`."""

    __tablename__ = "resultado_laboratorio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_episodio: Mapped[str] = mapped_column(
        String(_LONGITUD_CLAVE_HEX), ForeignKey("episodio.id_episodio"), index=True, nullable=False
    )
    id_estudio: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("estudio.id_estudio"), index=True, nullable=True
    )
    id_medico: Mapped[str | None] = mapped_column(String(_LONGITUD_CLAVE_HEX), nullable=True)
    analito: Mapped[str] = mapped_column(String, nullable=False)
    seccion: Mapped[str] = mapped_column(String, nullable=False)
    valor_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    valor_texto: Mapped[str | None] = mapped_column(String, nullable=True)
    unidad: Mapped[str | None] = mapped_column(String, nullable=True)
    ref_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    ref_max: Mapped[float | None] = mapped_column(Float, nullable=True)


class MedicionEco(Base):
    """Medidas de eco -- ancha: columnas fijas para el set clínico chico y estable. Medidas no
    reconocidas caen a `adicionales` en vez de perderse (ver `destinos/postgres.py::_PIVOTE_MEDIDAS_ECO`)."""

    __tablename__ = "medicion_eco"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_episodio: Mapped[str] = mapped_column(
        String(_LONGITUD_CLAVE_HEX), ForeignKey("episodio.id_episodio"), index=True, nullable=False
    )
    id_estudio: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("estudio.id_estudio"), index=True, nullable=True
    )
    id_medico_solicitante: Mapped[str | None] = mapped_column(String(_LONGITUD_CLAVE_HEX), nullable=True)
    id_medico_informante: Mapped[str | None] = mapped_column(String(_LONGITUD_CLAVE_HEX), nullable=True)
    id_matricula_informante: Mapped[str | None] = mapped_column(String(_LONGITUD_CLAVE_HEX), nullable=True)
    ao: Mapped[str | None] = mapped_column(String, nullable=True)
    ai: Mapped[str | None] = mapped_column(String, nullable=True)
    ddvi: Mapped[str | None] = mapped_column(String, nullable=True)
    dsvi: Mapped[str | None] = mapped_column(String, nullable=True)
    fa: Mapped[str | None] = mapped_column(String, nullable=True)
    septum: Mapped[str | None] = mapped_column(String, nullable=True)
    p_posterior: Mapped[str | None] = mapped_column(String, nullable=True)
    unidades: Mapped[dict | None] = mapped_column(_JsonPortable, nullable=True)
    adicionales: Mapped[dict | None] = mapped_column(_JsonPortable, nullable=True)


class TextoSeccionEco(Base):
    """Una fila por sección de texto libre del eco (motilidad, conclusiones, etc.), ya sin PII."""

    __tablename__ = "texto_seccion_eco"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_episodio: Mapped[str] = mapped_column(
        String(_LONGITUD_CLAVE_HEX), ForeignKey("episodio.id_episodio"), index=True, nullable=False
    )
    seccion: Mapped[str] = mapped_column(String, nullable=False)
    texto: Mapped[str] = mapped_column(String, nullable=False)


class Cuarentena(Base):
    """Registro terminal de fallo por documento con metadata de ubicación segura -- nunca un
    mensaje crudo, nunca contenido del documento."""

    __tablename__ = "cuarentena"
    __table_args__ = (
        # Un documento produce como mucho un apartado por corrida; NULL no colisiona con NULL, sin corrida no hay garantía.
        UniqueConstraint("corrida_id", "id_documento", name="uq_cuarentena_corrida_documento"),
        Index("ix_cuarentena_corrida_creado", "corrida_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_documento: Mapped[str] = mapped_column(String, index=True, nullable=False)
    etapa: Mapped[str] = mapped_column(String, nullable=False)
    codigo: Mapped[str] = mapped_column(String, nullable=False)
    campo: Mapped[str | None] = mapped_column(String, nullable=True)
    pagina: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tipo_documento: Mapped[str | None] = mapped_column(String, nullable=True)
    # Exclusivos de ARTEFACTO_SOBRETAMANO: números, nunca mensajes crudos.
    tamano_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tope_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    #: Sin FK hacia `corrida`, mismo motivo que en Estudio.
    corrida_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: Exclusivo de codigo == "parseo_incompleto": vocabulario cerrado, nunca texto libre.
    detalle_parseo: Mapped[str | None] = mapped_column(String, nullable=True)


class CorridaOrm(Base):
    """Estado durable de una ejecución administrativa del pipeline. El gate de "una corrida a
    la vez" es un índice único parcial `WHERE activa` -- la base lo decide atómicamente entre
    procesos, no un `threading.Lock` en memoria que no protegería contra otro proceso.
    `LanzadorCorrida.lanzar()` traduce su violación a `CorridaEnCursoError`."""

    __tablename__ = "corrida"
    __table_args__ = (
        Index(
            "ux_corrida_una_activa",
            "activa",
            unique=True,
            sqlite_where=sa_text("activa"),
            postgresql_where=sa_text("activa"),
        ),
    )

    id_corrida: Mapped[str] = mapped_column(String(36), primary_key=True)
    estado: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Dato de persistencia para el índice único parcial, mantenida por RepositorioCorridas, no por el dominio.
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora_utc, onupdate=_ahora_utc, nullable=False
    )
    # NULL en corridas creadas antes de esta columna: sin este dato, reintentar_corrida no admite reintento.
    ruta_autorizada: Mapped[str | None] = mapped_column(String, nullable=True)


class DocumentoCorridaOrm(Base):
    """Documento inventariado; la huella es idempotente dentro de su corrida."""

    __tablename__ = "documento_corrida"
    __table_args__ = (
        UniqueConstraint("corrida_id", "huella_contenido", name="uq_documento_corrida_huella"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Sin índice propio: el prefijo de uq_documento_corrida_huella ya cubre consultas por corrida_id solo.
    corrida_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("corrida.id_corrida"), nullable=False
    )
    huella_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    ruta_autorizada: Mapped[str] = mapped_column(String, nullable=False)
    estado: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora_utc, onupdate=_ahora_utc, nullable=False
    )
