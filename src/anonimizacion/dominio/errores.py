"""Jerarquía de errores del dominio.
Ningún error transporta el mensaje crudo de la excepción original: podría contener PII."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .referencias import validar_campo_reconciliacion
from .tipos_documento import TipoDocumento


class EtapaDocumento(str, Enum):
    """Etapas permitidas para metadata segura de errores."""

    EXTRACCION = "extraccion"
    DETECCION = "deteccion"
    PARSEO = "parseo"
    RECONCILIACION = "reconciliacion"
    DETECCION_PII = "deteccion_pii"
    PSEUDONIMIZACION = "pseudonimizacion"
    SALIDA = "salida"
    INGESTA = "ingesta"
    # Documento inventariado cuyo proceso hijo murió antes de llegar a EXTRACCION.
    DESPACHO = "despacho"


class CodigoErrorDocumento(str, Enum):
    """Códigos de fallo terminal — todos van a cuarentena, salvo `CAMPO_NO_EXTRAIDO`.
    Los primeros cuatro son determinísticos; `ERROR_TRANSITORIO_AGOTADO` puede reintentarse."""

    TIPO_NO_RECONOCIDO = "tipo_no_reconocido"
    PARSEO_INCOMPLETO = "parseo_incompleto"
    CLAVE_PII_NO_RESUELTA = "clave_pii_no_resuelta"
    # Más de un id_paciente candidato para el mismo id_alt_paciente (homónimos): revisión manual.
    CLAVE_PII_AMBIGUA = "clave_pii_ambigua"
    ERROR_TRANSITORIO_AGOTADO = "error_transitorio_agotado"
    EVIDENCIA_AUSENTE = "evidencia_ausente"
    EVIDENCIA_AMBIGUA = "evidencia_ambigua"
    VALOR_DISCREPANTE = "valor_discrepante"
    # Nivel CAMPO: el modelo afirma algo que el PDF no respalda.
    COBERTURA_INCOMPLETA = "cobertura_incompleta"
    COBERTURA_AMBIGUA = "cobertura_ambigua"
    # Dirección opuesta a COBERTURA_INCOMPLETA: el PDF trae un campo que el modelo no citó.
    # Única excepción a "todos van a cuarentena": es marca de completitud, no motivo de rechazo.
    CAMPO_NO_EXTRAIDO = "campo_no_extraido"
    # Nivel EPISODIO: el documento está bien, falla el grupo al que pertenece.
    EPISODIO_INCOMPLETO = "episodio_incompleto"
    EPISODIO_AMBIGUO = "episodio_ambiguo"
    # Apartado en FuenteLocal.listar() por superar el tope de tamaño; id_documento = sha256(ruta).
    ARTEFACTO_SOBRETAMANO = "artefacto_sobretamano"
    # Apartado en FuenteLocal.listar() por extensión fuera de _EXTENSIONES_SOPORTADAS.
    FORMATO_NO_SOPORTADO = "formato_no_soportado"
    # El proceso del sistema operativo que procesaba el grupo murió (típicamente OOM-kill).
    PROCESO_INTERRUMPIDO = "proceso_interrumpido"
    # El PDF se abrió y tiene páginas, pero ninguna trae texto nativo extraíble (escaneo).
    SIN_CAPA_DE_TEXTO = "sin_capa_de_texto"
    # El archivo no se pudo abrir como PDF (corrupto, cero páginas, o ruta inexistente).
    PDF_ILEGIBLE = "pdf_ilegible"


# Única fuente de verdad de "este código admite reintento"; ninguna otra capa copia esta lista.
CODIGOS_REINTENTABLES: frozenset[CodigoErrorDocumento] = frozenset(
    {
        CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA,
        CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO,
        CodigoErrorDocumento.EPISODIO_INCOMPLETO,
        CodigoErrorDocumento.PROCESO_INTERRUMPIDO,
    }
)


def es_reintentable(codigo: CodigoErrorDocumento) -> bool:
    """`True` si reprocesar el documento sin cambios puede tener éxito."""
    return codigo in CODIGOS_REINTENTABLES


class DetalleParseoIncompleto(str, Enum):
    """Qué encontró (o no encontró) el parser cuando lanzó `PARSEO_INCOMPLETO`.
    Vocabulario propio y cerrado, distinto de `campo` (etapa de reconciliación, no de parseo)."""

    # Ninguna página trajo un numero_peticion reconocible: nunca se armó ningún header.
    HEADER_AUSENTE = "header_ausente"
    NOMBRE_AUSENTE = "nombre_ausente"
    FECHA_AUSENTE = "fecha_ausente"
    FECHA_ILEGIBLE = "fecha_ilegible"
    HORA_ILEGIBLE = "hora_ilegible"
    # Dos páginas del mismo documento traen numero_peticion distintos.
    NUMERO_PETICION_INCONSISTENTE = "numero_peticion_inconsistente"


@dataclass(frozen=True)
class ErrorDocumento:
    """Registro terminal de fallo por documento; sin mensaje crudo, solo código."""

    id_documento: str
    etapa: str | EtapaDocumento
    codigo: CodigoErrorDocumento
    campo: str | None = None
    pagina: int | None = None
    tipo_documento: TipoDocumento | None = None
    # Exclusivos de ARTEFACTO_SOBRETAMANO: números, nunca mensajes crudos.
    tamano_bytes: int | None = None
    tope_bytes: int | None = None
    # None por compatibilidad con apartados anteriores a la trazabilidad por corrida.
    corrida_id: str | None = None
    detalle_parseo: DetalleParseoIncompleto | None = None

    def __post_init__(self) -> None:
        if self.campo is not None:
            validar_campo_reconciliacion(self.campo)
        if self.pagina is not None and self.pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        if self.tipo_documento is not None and not isinstance(self.tipo_documento, TipoDocumento):
            raise ValueError("tipo_documento debe pertenecer al catálogo")
        if self.detalle_parseo is not None:
            if not isinstance(self.detalle_parseo, DetalleParseoIncompleto):
                raise ValueError("detalle_parseo debe pertenecer al vocabulario cerrado")
            if self.codigo is not CodigoErrorDocumento.PARSEO_INCOMPLETO:
                raise ValueError("detalle_parseo es exclusivo de PARSEO_INCOMPLETO")


class ErrorParseo(Exception):
    """Error tipado que lanza cualquier etapa; el `codigo` reemplaza al mensaje crudo.
    `etapa` es obligatorio: un default fijo llevaría a cuarentena mal etiquetada."""

    def __init__(
        self,
        codigo: CodigoErrorDocumento,
        etapa: str | EtapaDocumento,
        campo: str | None = None,
        pagina: int | None = None,
        detalle_parseo: DetalleParseoIncompleto | None = None,
    ) -> None:
        if campo is not None:
            validar_campo_reconciliacion(campo)
        if pagina is not None and pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        if detalle_parseo is not None:
            if not isinstance(detalle_parseo, DetalleParseoIncompleto):
                raise ValueError("detalle_parseo debe pertenecer al vocabulario cerrado")
            if codigo is not CodigoErrorDocumento.PARSEO_INCOMPLETO:
                raise ValueError("detalle_parseo es exclusivo de PARSEO_INCOMPLETO")
        self.codigo = codigo
        self.etapa = etapa
        self.campo = campo
        self.pagina = pagina
        self.detalle_parseo = detalle_parseo
        super().__init__(codigo.value)  # codigo.value, no el repr del enum
