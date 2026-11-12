"""Marcadores del layout de ECG Mortara.
Verificados contra el texto real (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
"Fix: extracción con sort=True + firmas ECG reales"): el documento real trae "VENT. RATE"
(con punto), no "VENT RATE"/"PR-QRS-QT/QTC" concatenados como asumían los fixtures viejos.
"""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.ECG,
    marcadores=("MORTARA", "12SL", "P-R-T AXES", "VENT. RATE"),
)
