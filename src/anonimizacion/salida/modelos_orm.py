"""Modelos SQLAlchemy del esquema de salida (design.md, decisión Q1: storage híbrido).

Ocho tablas, incluyendo el estado durable de corridas para la decisión Q1 (más
`cuarentena`, no listada ahí pero requerida por spec `batch-processing` /
tasks.md 7.5 para persistir `ErrorDocumento`):

- `vinculo_paciente`: respaldo persistente de `ResolutorClaves` (Fase 6,
  `pseudonimizacion/resolutor_claves.py`). Debe preservar la MISMA semántica
  de ambigüedad de homónimos documentada ahí -- ver `destinos/postgres.py`,
  que es quien la implementa contra esta tabla (esta clase es solo el DDL).
- `episodio`: resultado de `pseudonimizacion/vinculacion.py` (clustering por
  ancla ±7 días).
- `medicion_ecg`: ANCHA, esquema fijo (`ContenidoEcg` de
  `parseo/ecg_mortara.py` ya trae un conjunto fijo y pequeño de medidas).
- `resultado_laboratorio`: LARGA/EAV. Rechazado explícitamente en design.md
  una columna por analito (sparse extremo, DDL nuevo por cada analito
  nuevo) -- el conjunto de analitos de `ContenidoLaboratorio` es variable
  entre estudios, a diferencia del ECG.
- `medicion_eco`: ANCHA -- a diferencia del laboratorio, el conjunto de
  medidas de un eco (AO/AI/DDVI/DSVI/FA/Septum/P.Posterior) es chico y fijo
  clínicamente, así que sí amerita columnas fijas (ver
  `destinos/postgres.py::_PIVOTE_MEDIDAS_ECO` para el pivote nombre->columna
  desde el `MedidaEco` genérico que entrega el parser).
- `texto_seccion_eco`: una fila por sección de texto libre del eco, ya sin
  PII (la depuración de PII en texto libre es responsabilidad de la
  detección de PII + el pipeline que la orquesta, Fase 5/8 -- esta tabla
  asume que el texto que recibe ya pasó por ahí).
- `corrida` y `documento_corrida`: estado durable y versionado para reanudar una corrida; la huella es única dentro de cada corrida.
- `cuarentena`: SOLO `id_documento` + `etapa` + `codigo` (ver
  `dominio/errores.py::ErrorDocumento` y `cuarentena.py`) -- nunca mensaje
  crudo, nunca contenido del documento (design.md, "Sin PII en cola, logs
  ni DLQ").

`adicionales`/`unidades` usan `sqlalchemy.JSON` con variante `JSONB` para
Postgres (`Column(JSON().with_variant(JSONB(), "postgresql"))`): en
producción (Postgres) esto compila a JSONB real, tal como pide design.md;
en el entorno de desarrollo de este repo (sin Postgres instalado, ver nota
en `tests/salida/`) SQLAlchemy usa el `JSON` genérico, que en SQLite se
guarda como `TEXT` con (de)serialización automática -- mismo comportamiento
a nivel de aplicación, sin comprometer el tipo real de producción. Nunca se
usa como camino de acceso primario de queries (design.md, decisión Q1):
ninguna columna JSON participa de un índice ni de un filtro `WHERE` en este
módulo.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Time, UniqueConstraint
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

    `id_paciente` queda en `NULL` cuando `ambiguo=True`: una vez marcado
    ambiguo no hay ningún `id_paciente` candidato seguro (ver
    `pseudonimizacion/resolutor_claves.py`, docstring de `ResolutorClaves`).
    """

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
    """Un documento clinico publicado, con su momento propio.

    Existe porque `episodio.fecha_ancla` es la fecha del GRUPO (ventana +-7 dias),
    no la de cada estudio: sin esta tabla el delta entre el ECG y el laboratorio
    de un mismo episodio no es computable en SQL ni siquiera en dias. Las tablas
    de mediciones cuelgan de aca por `id_estudio`.

    `hora_estudio` es `TIME WITHOUT TIME ZONE`: los documentos no declaran huso y
    no se infiere ninguno, asi que la hora es naive por construccion -- hora local
    del instituto, tal como figura en el papel.

    `precision_hora` NO es derivable de `hora_estudio` (ver
    `dominio/precision_hora.py`): un laboratorio a las `08:45` se persiste
    `08:45:00`, identico a un ECG con esa hora. Y `hora_estudio IS NULL` con
    `precision_hora = 'ausente'` significa "el documento no la trae", nunca
    medianoche ni un faltante por error -- un documento cuya hora es ilegible va
    a cuarentena y no llega a producir fila aca.
    """

    __tablename__ = "estudio"

    id_estudio: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_episodio: Mapped[str] = mapped_column(
        String(_LONGITUD_CLAVE_HEX), ForeignKey("episodio.id_episodio"), index=True, nullable=False
    )
    tipo_documento: Mapped[str] = mapped_column(String, nullable=False)
    fecha_estudio: Mapped[date] = mapped_column(Date, nullable=False)
    hora_estudio: Mapped[time | None] = mapped_column(Time, nullable=True)
    precision_hora: Mapped[str] = mapped_column(String, nullable=False)


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
    adicionales: Mapped[dict | None] = mapped_column(_JsonPortable, nullable=True)


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
    """Medidas de eco -- ancha: columnas fijas para el set clínico chico y estable.

    Ver `destinos/postgres.py::_PIVOTE_MEDIDAS_ECO` para cómo se pivotea el
    `tuple[MedidaEco, ...]` genérico del parser a estas columnas; medidas no
    reconocidas caen a `adicionales` en vez de perderse.
    """

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
    """Registro terminal de fallo por documento con metadata de ubicación segura.

    Nunca un mensaje crudo, nunca contenido del documento (ver
    `dominio/errores.py::ErrorDocumento`, `cuarentena.py`).
    """

    __tablename__ = "cuarentena"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_documento: Mapped[str] = mapped_column(String, index=True, nullable=False)
    etapa: Mapped[str] = mapped_column(String, nullable=False)
    codigo: Mapped[str] = mapped_column(String, nullable=False)
    campo: Mapped[str | None] = mapped_column(String, nullable=True)
    pagina: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tipo_documento: Mapped[str | None] = mapped_column(String, nullable=True)
    # Exclusivos de `ARTEFACTO_SOBRETAMANO` (ver `dominio/errores.py::ErrorDocumento`):
    # números, no mensajes crudos. Permiten ajustar el tope de tamaño leyendo
    # este reporte, sin adivinar ni re-derivar nada del filesystem.
    tamano_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tope_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)


class CorridaOrm(Base):
    """Estado durable de una ejecución administrativa del pipeline."""

    __tablename__ = "corrida"

    id_corrida: Mapped[str] = mapped_column(String(36), primary_key=True)
    estado: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora_utc, onupdate=_ahora_utc, nullable=False
    )


class DocumentoCorridaOrm(Base):
    """Documento inventariado; la huella es idempotente dentro de su corrida."""

    __tablename__ = "documento_corrida"
    __table_args__ = (
        UniqueConstraint("corrida_id", "huella_contenido", name="uq_documento_corrida_huella"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    corrida_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("corrida.id_corrida"), index=True, nullable=False
    )
    huella_contenido: Mapped[str] = mapped_column(String(64), nullable=False)
    ruta_autorizada: Mapped[str] = mapped_column(String, nullable=False)
    estado: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora_utc, onupdate=_ahora_utc, nullable=False
    )
