"""Marcadores del layout de laboratorio general.

Defecto medido (comparando el puntaje contra el texto estructural sintético
-- 4/4 marcadores -- contra el mismo documento extraído con PyMuPDF desde el
PDF real del Instituto de Cardiología de Corrientes -- 3/4 marcadores):
"QUIMICA CLINICA" (sin tilde) nunca aparece en el documento real. El
encabezado real trae tilde, "QUÍMICA CLÍNICA", y ni `detectar_tipo`
(`deteccion/detector_tipo.py`) ni `Firma.puntaje` (`firmas/base.py`)
normalizan acentos -- comparan el texto en mayúsculas tal cual viene de
PyMuPDF contra el literal declarado, así que "Í" (con tilde) nunca matchea
"I" (sin tilde). Mismo defecto de fondo que el fix de `redaccion.py`
(commit "fix(pii): tolera acentos..."), pero en la capa de detección, no de
redacción.

"QUIMICA CLINICA" (sin tilde) se conserva: no aparece en el documento real,
pero sí lo usan `tests/fixtures/v1/documentos.py`, `tests/fixtures/
pdf_sintetico.py` y varios tests de parseo/reconciliación como layout
sintético legado -- sacarlo rompería esos fixtures sin necesidad, y no hace
daño dejarlo (`Firma.puntaje` sólo suma evidencia, no exige un marcador
puntual). "QUÍMICA CLÍNICA" (con tilde) se agrega como marcador nuevo,
verificado contra el texto real extraído del PDF.
"""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.LABORATORIO,
    marcadores=("HEMATOLOGIA", "HEMOSTASIA", "QUIMICA CLINICA", "QUÍMICA CLÍNICA", "IONOGRAMA"),
)
