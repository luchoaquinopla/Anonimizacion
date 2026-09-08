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

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Time, UniqueConstraint
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
    #: Identidad estable del documento (HMAC del sha256, ver
    #: `pseudonimizacion/claves.py::generar_clave_documento`). Es lo que permite
    #: reconocer un reprocesamiento y no duplicar. Nace OPCIONAL y sin relleno
    #: hacia atras: las filas escritas antes de este cambio no tienen forma de
    #: derivarla sin releer el documento original, y `NULL` no colisiona con
    #: `NULL` en la restriccion unica, asi que conviven sin romper nada.
    clave_documento: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Corrida que escribio esta fila (spec `trazabilidad-por-corrida`,
    #: Requisito 1). Sin FK hacia `corrida` a proposito (design.md): la tabla
    #: `corrida` es plano de control, esta es plano de datos, y una FK haria
    #: que la fila administrativa fuera requisito para escribir salida clinica.
    corrida_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: Momento propio de esta fila, distinto de `episodio.fecha_ancla` -- sin
    #: el, no hay forma de calcular una tasa de avance (spec
    #: `trazabilidad-por-corrida`, Requisito 1). `NULL` para las filas
    #: preexistentes: no se sabe cuando se escribieron, y un relleno con la
    #: fecha de la migracion seria una mentira.
    #: `default=_ahora_utc` (no `server_default`), calcado del docstring del
    #: campo arriba y de `design.md` ("NULL = no se sabe cuándo, que es la
    #: verdad; un `server_default` las dataría con el momento de la migración,
    #: una mentira"): las filas escritas por Alembic/`create_all` sin este
    #: default no llevan timestamp, las escritas por el pipeline desde acá sí.
    creado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=True)
    #: Marca de completitud (requisito "que un campo nuevo no rompa el
    #: parseo, sino que sea un aviso" -- ver `dominio/errores.py::CodigoErrorDocumento.CAMPO_NO_EXTRAIDO`
    #: y `dominio/modelos.py::RegistroAnonimizado.campos_no_extraidos`).
    #: Nullable, sin backfill (mismo criterio que `ruta_autorizada` en `corrida`,
    #: migración `0011`): las filas escritas antes de este cambio no tienen
    #: forma de saber si estaban completas, y `NULL` es la verdad ("no se
    #: sabe"), no `True` inventado. Las filas nuevas del pipeline SIEMPRE la
    #: completan (`RegistroAnonimizado.completo`, derivada de
    #: `campos_no_extraidos`, nunca un segundo estado independiente).
    completo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: `id_campo` (vocabulario cerrado, `dominio/referencias.py`) que el PDF
    #: traía y el parser no citó -- NUNCA texto libre ni contenido del
    #: documento. Puede repetir un `id_campo` (una ocurrencia por instancia
    #: faltante, p.ej. varias filas de `laboratorio.resultado`). `NULL` para
    #: las filas preexistentes, mismo criterio que `completo` arriba; las
    #: filas nuevas siempre traen una lista (`[]` si `completo` es `True`).
    campos_no_extraidos: Mapped[list[str] | None] = mapped_column(_JsonPortable, nullable=True)


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
    __table_args__ = (
        # Clave de idempotencia (design.md, Decisión 4): un documento produce
        # como mucho un apartado por corrida. `NULL` no colisiona con `NULL`
        # ni en SQLite ni en Postgres, así que las filas sin corrida (el
        # script sin corrida, los tests, los fixtures legados) conviven sin
        # ninguna garantía -- eso es lo que ya pasaba, y sigue pasando.
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
    # Exclusivos de `ARTEFACTO_SOBRETAMANO` (ver `dominio/errores.py::ErrorDocumento`):
    # números, no mensajes crudos. Permiten ajustar el tope de tamaño leyendo
    # este reporte, sin adivinar ni re-derivar nada del filesystem.
    tamano_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tope_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    #: Corrida que produjo este apartado (spec `trazabilidad-por-corrida`,
    #: Requisito 1). Sin FK hacia `corrida`, mismo motivo que en `Estudio`.
    corrida_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    #: Exclusivo de `codigo == "parseo_incompleto"` (ver
    #: `dominio/errores.py::DetalleParseoIncompleto`): qué faltó o fue
    #: ilegible durante el parseo -- vocabulario cerrado, nunca texto libre.
    detalle_parseo: Mapped[str | None] = mapped_column(String, nullable=True)


class CorridaOrm(Base):
    """Estado durable de una ejecución administrativa del pipeline.

    `activa` + `ux_corrida_una_activa` (revisión adversarial ronda 3,
    hallazgo 4, feature `despachador-desde-el-panel`): el gate de "una
    corrida a la vez" NO puede vivir sólo en un `threading.Lock` de
    `ServicioCorridasReal` -- eso sólo protege al panel contra SUS PROPIAS
    peticiones concurrentes, nunca contra `scripts/procesar_carpeta.py`
    (OTRO proceso) lanzando una corrida real mientras el panel ya está
    procesando una. Confirmado: `procesar_carpeta.py` no llama
    `listar_corridas_no_terminales` en ningún punto -- no tiene gate propio.

    `activa` es `True` mientras `estado` NO es terminal
    (`RepositorioCorridas` la mantiene sincronizada en cada escritura, nunca
    se setea a mano). El índice único parcial `ux_corrida_una_activa`
    (`WHERE activa`, en la migración correspondiente y acá para que
    `Base.metadata.create_all` -- usado por los tests rápidos con SQLite --
    también lo exija) hace que la BASE rechace crear una segunda fila
    `activa=True` mientras ya existe una, sin importar qué proceso ni en qué
    orden -- Postgres decide atómicamente, no un lock en memoria de un solo
    proceso. Todas las filas con `activa=False` (terminales) quedan FUERA
    del índice parcial, así que nunca compiten entre sí: sólo puede haber
    UNA fila `activa=True` en total, nunca más.

    `LanzadorCorrida.lanzar()` traduce la violación de esta restricción a
    `CorridaEnCursoError` -- ver ese módulo.
    """

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
    # Ver el docstring de la clase: mantenida por `RepositorioCorridas`, no
    # por el dominio -- es un dato de PERSISTENCIA (para el índice único
    # parcial), no una transición de `Corrida.avanzar_a`.
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_ahora_utc, nullable=False)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_ahora_utc, onupdate=_ahora_utc, nullable=False
    )
    # Raíz autorizada inventariada por `LanzadorCorrida.lanzar` (feature
    # `reanudacion-de-corridas`). Nullable: las corridas creadas antes de esta
    # columna quedan en `NULL` -- no se rellena retroactivamente, mismo
    # criterio que `estudio.creado_en` en la migración `0008`. Sin este dato
    # `reintentar_corrida` no puede reconstruir la raíz autorizada que exige
    # `despacho_paralelo.inicializar_trabajador` (`entrada`), así que una
    # corrida vieja sin este campo no admite reintento -- ver
    # `web/reintento_corrida.py`.
    ruta_autorizada: Mapped[str | None] = mapped_column(String, nullable=True)


class DocumentoCorridaOrm(Base):
    """Documento inventariado; la huella es idempotente dentro de su corrida."""

    __tablename__ = "documento_corrida"
    __table_args__ = (
        UniqueConstraint("corrida_id", "huella_contenido", name="uq_documento_corrida_huella"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Sin índice propio a propósito (migración 0008 lo elimina): el prefijo de
    # `uq_documento_corrida_huella (corrida_id, huella_contenido)` ya cubre
    # cualquier consulta por `corrida_id` solo. Un índice aparte sería
    # estrictamente redundante y se pagaría en cada una de las inserciones
    # del inventario sin aportar nada (design.md, "Los dos índices de una
    # columna de `documento_corrida`, revisados de verdad").
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
