"""Marcadores del layout de ECG Mortara.

Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
extracción con sort=True + firmas ECG reales"): "VENT RATE" (sin punto) y
"PR-QRS-QT/QTC" fueron verificados contra el texto real de un ECG Mortara y
NUNCA aparecen tal cual -- el documento real trae "VENT. RATE" (con punto) y
"PR interval"/"QRS duration"/"QT/QTc" como etiquetas separadas, nunca
concatenadas en una sola cadena. Como resultado, ningún ECG real era
reconocido por `detectar_tipo` (caía en `TIPO_NO_RECONOCIDO` antes de
llegar al parser). "12SL" (nombre del algoritmo propietario del equipo) y
"P-R-T AXES" sí aparecen literalmente y se agregan como marcadores nuevos.
"VENT. RATE" (con punto) se agrega también, como marcador redundante
adicional (`Firma.coincide` usa `any()`: con que uno matchee alcanza).
"MORTARA" se mantiene: no aparece en el/los documento(s) verificados hasta
ahora, pero podría aparecer en otro layout Mortara no visto todavía (p. ej.
pie de página) -- dejarlo no hace daño si no matchea.
"""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.ECG,
    marcadores=("MORTARA", "12SL", "P-R-T AXES", "VENT. RATE"),
)
