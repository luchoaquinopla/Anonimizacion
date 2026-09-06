"""Traducción de códigos internos de cuarentena a texto llano.

Única fuente de esta tabla. La comparten `reporte_cuarentena.py` (que la
usa para el detalle por documento) y `plantilla_panel.py` (que la usa para
la columna "Motivos" del embudo por etapa) -- ninguno de los dos la copia.
Copiarla en dos lugares es la forma más segura de que se desincronicen: el
día que alguien agregue o corrija una explicación en un lado y no en el
otro, las dos pantallas dirían cosas distintas del mismo código de error.

Un código sin traducción NO se descarta ni rompe nada: cada llamador decide
su propio "último recurso" (mostrar el código crudo, por ejemplo) -- esta
tabla sólo mapea lo que sabe traducir.
"""

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
    # `artefacto_sobretamano` no está acá en `reporte_cuarentena.py`: ese
    # módulo tiene una rama propia (`_explicar`) que arma un mensaje con el
    # tamaño real y el tope configurado, tomados de la fila de `Cuarentena`.
    # `plantilla_panel.py` sólo ve conteos agregados por código (sin esos
    # bytes), así que necesita una entrada genérica acá para no mostrar el
    # código crudo.
    "artefacto_sobretamano": "El archivo excede el tamaño máximo permitido.",
}
