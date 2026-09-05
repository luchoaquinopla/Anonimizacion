"""Jerarquía de errores del dominio.

Ningún error transporta el mensaje crudo de la excepción original: podría
contener PII (ver design.md, decisión "Sin PII en cola, logs ni DLQ").
"""

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


class CodigoErrorDocumento(str, Enum):
    """Códigos de fallo terminal — todos van a cuarentena.

    Los primeros cuatro son determinísticos: nunca se reintentan, un
    reproceso sin cambios produce el mismo fallo (ver design.md,
    "Aislamiento de fallo y política de reintentos"). `ERROR_TRANSITORIO_AGOTADO`
    es distinto: se alcanza después de agotar los reintentos de un error
    transitorio (IO/conexión) -- ver `pipeline/ejecutor.py`. Reprocesar ESE
    documento más tarde puede tener éxito (el error original no era
    determinístico), a diferencia de los otros cuatro.
    """

    TIPO_NO_RECONOCIDO = "tipo_no_reconocido"
    PARSEO_INCOMPLETO = "parseo_incompleto"
    CLAVE_PII_NO_RESUELTA = "clave_pii_no_resuelta"
    # Hay más de un `id_paciente` candidato para el mismo `id_alt_paciente`
    # (homónimos: mismo nombre+fecha_nac, DNI distinto). A diferencia de
    # CLAVE_PII_NO_RESUELTA (todavía no hay ningún puente, reprocesar más
    # tarde puede resolverlo solo), esto requiere revisión manual --
    # reprocesar no lo arregla.
    CLAVE_PII_AMBIGUA = "clave_pii_ambigua"
    # Ver docstring de la clase: terminal tras agotar reintentos de un error
    # transitorio (`pipeline/ejecutor.py`, `trabajadores/politica_reintentos.py`).
    ERROR_TRANSITORIO_AGOTADO = "error_transitorio_agotado"
    EVIDENCIA_AUSENTE = "evidencia_ausente"
    EVIDENCIA_AMBIGUA = "evidencia_ambigua"
    VALOR_DISCREPANTE = "valor_discrepante"
    # COBERTURA_*: nivel CAMPO. Un dato del documento no pudo citarse contra una
    # unica fuente del PDF (`reconciliacion/inventario.py`,
    # `reconciliacion/laboratorio_general.py`). Es un problema del parser o del
    # layout: reprocesar el mismo documento no lo arregla solo.
    COBERTURA_INCOMPLETA = "cobertura_incompleta"
    COBERTURA_AMBIGUA = "cobertura_ambigua"
    # EPISODIO_*: nivel EPISODIO. El documento esta bien; lo que falla es el
    # grupo al que pertenece (`pipeline/coordinador_episodios.py`). Se separan de
    # COBERTURA_* porque son problemas operativos distintos: "a este paciente le
    # falta el ecocardiograma" se resuelve pidiendolo al origen, "no pude
    # verificar el potasio" es del parser. Antes compartian codigo y solo podian
    # distinguirse por la convencion implicita de que el coordinador nunca llena
    # `campo`/`pagina` -- fragil ante cualquier productor nuevo.
    EPISODIO_INCOMPLETO = "episodio_incompleto"
    EPISODIO_AMBIGUO = "episodio_ambiguo"
    # Artefacto apartado en `FuenteLocal.listar()` (`ingesta/fuente.py`) por
    # superar el tope de tamaño configurado. `id_documento` es el sha256 de la
    # RUTA, no del contenido -- el archivo nunca se lee (ver `tamano_bytes`/
    # `tope_bytes` abajo, y design.md "puerto de ingesta", Decisión 3).
    ARTEFACTO_SOBRETAMANO = "artefacto_sobretamano"


@dataclass(frozen=True)
class ErrorDocumento:
    """Registro terminal de fallo por documento; sin mensaje crudo, solo código."""

    id_documento: str
    etapa: str | EtapaDocumento
    codigo: CodigoErrorDocumento
    campo: str | None = None
    pagina: int | None = None
    tipo_documento: TipoDocumento | None = None
    # Exclusivos de `ARTEFACTO_SOBRETAMANO` (ingesta): números, no mensajes
    # crudos -- coherente con "sin PII en cola, logs ni DLQ". Permiten ajustar
    # el tope de tamaño leyendo el reporte, sin re-derivar nada del filesystem.
    tamano_bytes: int | None = None
    tope_bytes: int | None = None
    # Corrida que produjo este apartado (spec `trazabilidad-por-corrida`,
    # Requisito 1). Opcional al final, mismo precedente que `clave_documento`
    # en `RegistroAnonimizado`: nace `None` para no romper fixtures ni
    # llamadores existentes -- incluidos los apartados por sobretamaño en
    # `FuenteLocal`, que ocurren antes de que exista ninguna corrida.
    corrida_id: str | None = None

    def __post_init__(self) -> None:
        if self.campo is not None:
            validar_campo_reconciliacion(self.campo)
        if self.pagina is not None and self.pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        if self.tipo_documento is not None and not isinstance(self.tipo_documento, TipoDocumento):
            raise ValueError("tipo_documento debe pertenecer al catálogo")


class ErrorParseo(Exception):
    """Error tipado que lanza cualquier etapa; el `codigo` reemplaza al mensaje crudo.

    `etapa` es obligatorio (sin default): el código puede originarse en detección,
    parseo o pseudonimización, y un default fijo llevaría a cuarentena mal etiquetada.
    """

    def __init__(
        self,
        codigo: CodigoErrorDocumento,
        etapa: str | EtapaDocumento,
        campo: str | None = None,
        pagina: int | None = None,
    ) -> None:
        if campo is not None:
            validar_campo_reconciliacion(campo)
        if pagina is not None and pagina < 1:
            raise ValueError("pagina debe comenzar en 1")
        self.codigo = codigo
        self.etapa = etapa
        self.campo = campo
        self.pagina = pagina
        super().__init__(codigo.value)  # str(excepcion) legible; codigo.value, no el enum repr
