"""Traducción de códigos internos de cuarentena a texto llano. Única fuente, compartida
por `reporte_cuarentena.py` y `plantilla_panel.py` -- ninguno la copia."""

from __future__ import annotations

EXPLICACION_POR_CODIGO: dict[str, str] = {
    "episodio_incompleto": "Al grupo de este paciente le falta al menos un tipo de estudio.",
    "episodio_ambiguo": "El grupo trae dos estudios del mismo tipo y no se puede saber cuál corresponde.",
    "tipo_no_reconocido": "No se pudo identificar de qué tipo de estudio se trata.",
    "parseo_incompleto": "El documento no se pudo leer completo.",
    "evidencia_ausente": "Un dato esperado no aparece en el documento.",
    "evidencia_ambigua": "Un dato aparece más de una vez y no se puede elegir cuál es.",
    "valor_discrepante": "Un dato extraído no coincide con el documento original.",
    "cobertura_incompleta": "Un dato no pudo verificarse contra el documento original.",
    "cobertura_ambigua": "Un dato tiene más de una fuente posible en el documento.",
    "error_transitorio_agotado": "Se reintentó varias veces y siguió fallando.",
    "clave_pii_no_resuelta": "Todavía no hay forma de saber a qué paciente pertenece.",
    "clave_pii_ambigua": "Hay más de un paciente posible con el mismo nombre y fecha de nacimiento.",
    # Entrada genérica: `reporte_cuarentena.py` arma este mensaje con tamaño/tope reales.
    "artefacto_sobretamano": "El archivo excede el tamaño máximo permitido.",
    "formato_no_soportado": "El archivo no es un formato que el sistema pueda procesar.",
    # Distinto de `error_transitorio_agotado`: acá falló el PROCESO, no el documento.
    "proceso_interrumpido": "El proceso que lo estaba procesando se interrumpió inesperadamente (no es un problema del documento).",
    "sin_capa_de_texto": "El documento es un escaneo sin texto extraíble: necesita pasar por OCR.",
    "pdf_ilegible": "El archivo no se pudo abrir como PDF (corrupto, vacío o inexistente).",
}

#: Traducción del detalle de un `parseo_incompleto` (ver `dominio/errores.py::DetalleParseoIncompleto`).
EXPLICACION_POR_DETALLE_PARSEO: dict[str, str] = {
    "header_ausente": "No se encontró ningún encabezado reconocible en el documento.",
    "nombre_ausente": "Falta el nombre del paciente en el encabezado.",
    "fecha_ausente": "Falta la fecha del estudio en el encabezado.",
    "fecha_ilegible": "La fecha del estudio tiene un formato irreconocible.",
    "hora_ilegible": "La hora de extracción tiene un formato irreconocible.",
    "numero_peticion_inconsistente": "Dos páginas del documento traen números de petición distintos.",
}
