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
    # Capa de gestión de procesos (openspec `paralelismo-de-procesamiento`
    # PR 3, `trabajadores/despacho_paralelo.py`): un documento ya inventariado
    # (paso por INGESTA) cuyo proceso hijo murió antes de que el pipeline
    # llegara a EXTRACCION -- no es ninguna de las etapas de arriba, porque
    # el documento nunca entró al pipeline en sí. Distinguirla de las demás
    # es lo que permite que `web/embudo_corrida.py::calcular_embudo` cierre
    # el desglose por etapa sin perder conteos (antes de esto, un `etapa`
    # fuera del vocabulario fijo de `ETAPAS_EMBUDO` se sumaba al total global
    # pero desaparecía del desglose por etapa -- ver ese módulo).
    DESPACHO = "despacho"


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
    # Artefacto apartado en `FuenteLocal.listar()` (`ingesta/fuente.py`) por
    # tener una extensión fuera de `_EXTENSIONES_SOPORTADAS`. Distinto de
    # `TIPO_NO_RECONOCIDO` (ese es de parseo: el archivo SE ABRIÓ como PDF y
    # no se pudo clasificar su contenido) -- acá el archivo ni se abre. Igual
    # que `ARTEFACTO_SOBRETAMANO`, `id_documento` es el sha256 de la RUTA: no
    # se lee el contenido de un formato que ni siquiera sabemos parsear.
    FORMATO_NO_SOPORTADO = "formato_no_soportado"
    # El proceso del sistema operativo que procesaba este grupo murió
    # (openspec `paralelismo-de-procesamiento` PR 3, `despacho_paralelo.py`
    # -- típicamente un OOM-kill) y se agotaron los reintentos de
    # aislamiento SIN que el documento en sí mostrara ningún problema
    # detectado. Deliberadamente DISTINTO de `ERROR_TRANSITORIO_AGOTADO`
    # (ese es un fallo de IO/conexión DENTRO del pipeline, sobre un
    # documento que sí llegó a ejecutarse) -- acá el documento puede no
    # haber llegado a correr en absoluto. Confundir los dos códigos le
    # ocultaría al operador que la causa no está en el contenido del
    # documento sino en el proceso que lo procesaba (memoria, infra).
    PROCESO_INTERRUMPIDO = "proceso_interrumpido"
    # `extraccion/texto_pymupdf.py`: el PDF se abrió y tiene páginas, pero
    # NINGUNA trae texto nativo extraíble -- típicamente un escaneo (imagen
    # sin capa de texto por debajo). Es la distinción de mayor valor
    # operativo de todo este vocabulario: le dice al instituto "estos
    # estudios son escaneos, necesitan pasar por OCR", una acción
    # completamente distinta de "revisar el layout del parser". Antes de
    # este código, compartía `PARSEO_INCOMPLETO` con `PDF_ILEGIBLE`
    # (corrupto) y con cualquier campo de header ausente -- indistinguibles
    # entre sí, obligando a abrir cada documento a mano para saber cuál de
    # las tres cosas pasó.
    SIN_CAPA_DE_TEXTO = "sin_capa_de_texto"
    # `extraccion/texto_pymupdf.py`: el archivo NO se pudo ni siquiera abrir
    # como PDF (bytes corruptos, cero páginas, o -- vía `extraer_texto`, uso
    # de CLI/tests -- la ruta no existe). Distinto de `SIN_CAPA_DE_TEXTO`:
    # ahí el PDF es válido y tiene páginas, acá el documento en sí está roto
    # o no está. La acción es distinta: pedir el archivo de nuevo al origen,
    # no pasar nada por OCR.
    PDF_ILEGIBLE = "pdf_ilegible"


# Única fuente de verdad de "este código admite reintento" (ver el docstring
# de la clase de arriba para el criterio). Ninguna otra capa -- en particular
# `web/reintento_corrida.py`, que traduce esto a un plan de reintento por
# corrida -- puede mantener su propia copia de esta lista: dos copias de la
# misma regla es exactamente la clase de bomba de tiempo que este proyecto ya
# documentó haber sufrido con el clustering de episodios
# (`pipeline/coordinador_episodios.py`).
#
# `EPISODIO_AMBIGUO` NO está acá (a diferencia de `EPISODIO_INCOMPLETO`):
# significa que hay más de un candidato de agrupamiento posible para el mismo
# documento -- requiere revisión manual, igual que `CLAVE_PII_AMBIGUA`.
# Reprocesar sin que un humano resuelva la ambigüedad reproduce el mismo
# empate.
CODIGOS_REINTENTABLES: frozenset[CodigoErrorDocumento] = frozenset(
    {
        CodigoErrorDocumento.CLAVE_PII_NO_RESUELTA,
        CodigoErrorDocumento.ERROR_TRANSITORIO_AGOTADO,
        CodigoErrorDocumento.EPISODIO_INCOMPLETO,
        CodigoErrorDocumento.PROCESO_INTERRUMPIDO,
    }
)


def es_reintentable(codigo: CodigoErrorDocumento) -> bool:
    """`True` si reprocesar el documento sin cambios puede tener éxito.

    Ver `CODIGOS_REINTENTABLES` para el porqué de cada código, y el docstring
    de `CodigoErrorDocumento` para la distinción determinístico/transitorio.
    """
    return codigo in CODIGOS_REINTENTABLES


class DetalleParseoIncompleto(str, Enum):
    """Qué encontró (o no encontró) el parser cuando lanzó `PARSEO_INCOMPLETO`.

    Decisión de diseño: exclusivo de `PARSEO_INCOMPLETO`, en un atributo
    tipado NUEVO (`ErrorDocumento.detalle_parseo`) en vez de extender el
    vocabulario de `campo` (`dominio/referencias.py::REFERENCIAS_PERMITIDAS`).
    Se descartó extender `campo` porque ese vocabulario tiene una semántica
    propia y posterior en el pipeline: identifica un dato YA RECONCILIADO
    contra el PDF (`COBERTURA_INCOMPLETA`, `VALOR_DISCREPANTE`, etc., todos
    en la etapa `reconciliacion`). Los seis valores de acá describen, en
    cambio, qué faltó o fue ilegible durante el PARSEO -- una etapa anterior,
    que ni siquiera llegó a producir un `DocumentoParseado` para reconciliar.
    Conflacionar ambos vocabularios obligaría a inventar entradas como
    `laboratorio.numero_peticion` (esa verificación no es un campo clínico
    reconciliable, es una consistencia estructural entre páginas) y a la vez
    permitiría que un código de PARSEO válido "ecg.nombre" filtrara,
    accidentalmente, en un chequeo pensado para RECONCILIACION. Dos
    vocabularios angostos, cada uno cerrado sobre su propia etapa, es más
    seguro que uno ancho compartido entre etapas con significados distintos.

    Como CUALQUIER metadata de `ErrorDocumento` (ver docstring del módulo):
    vocabulario cerrado, nunca texto libre, nunca contenido del documento.
    `ErrorDocumento.__post_init__` rechaza cualquier valor que no sea un
    miembro de este enum -- ver el test que lo demuestra pasando un string
    con forma de PII (`test_error_documento_rechaza_detalle_parseo_como_texto_libre`).
    """

    # `laboratorio_general.py`: ninguna página trajo un `numero_peticion`
    # reconocible -- nunca se armó ningún header, distinto de "se armó el
    # header pero falta nombre/fecha adentro".
    HEADER_AUSENTE = "header_ausente"
    # ECG, eco, laboratorio: el header se armó pero la etiqueta de nombre
    # nunca apareció.
    NOMBRE_AUSENTE = "nombre_ausente"
    # ECG, eco, laboratorio: idem, para la etiqueta de fecha del estudio.
    FECHA_AUSENTE = "fecha_ausente"
    # La etiqueta de fecha apareció, pero su valor no matchea ningún formato
    # de fecha conocido para ese equipo (`_parsear_fecha` lanza `ValueError`).
    FECHA_ILEGIBLE = "fecha_ilegible"
    # `laboratorio_general.py`: la hora de extracción está presente pero no
    # matchea ningún formato conocido -- cuarentena, no ausencia silenciosa
    # (Fase 8, mismo requisito documentado en el propio parser).
    HORA_ILEGIBLE = "hora_ilegible"
    # `laboratorio_general.py`: dos páginas del mismo documento traen
    # `numero_peticion` DISTINTOS -- páginas de dos estudios distintos
    # mezcladas en un solo artefacto.
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
    # Exclusivo de `PARSEO_INCOMPLETO` -- ver el docstring de
    # `DetalleParseoIncompleto` para la justificación de por qué es un
    # atributo tipado nuevo y no una extensión de `campo`.
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

    `etapa` es obligatorio (sin default): el código puede originarse en detección,
    parseo o pseudonimización, y un default fijo llevaría a cuarentena mal etiquetada.
    """

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
        super().__init__(codigo.value)  # str(excepcion) legible; codigo.value, no el enum repr
