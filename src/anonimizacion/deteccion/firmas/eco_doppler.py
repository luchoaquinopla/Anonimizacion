"""Marcadores del layout de ecocardiograma Doppler.

Defecto medido (ver `sdd/{...}/apply-progress` o el commit que corrige esto):
corriendo las firmas contra el texto real de un ecocardiograma del Instituto
de Cardiología de Corrientes, esta firma reconocía el documento por 1 de 3
marcadores declarados. "ECOCARDIOGRAMA DOPPLER" y "FRACCION DE ACORTAMIENTO"
NO aparecen en el documento real -- el real dice "SERVICIO DE
ECOCARDIOGRAFIA" / "ECOGRAFIA DOPPLER COLOR CARDIACA" y "FA" (no la forma
larga). Salieron de fixtures sintéticos que inventamos nosotros, nunca se
verificaron contra una muestra real. El mismo defecto ya había ocurrido con
ECG (ver docstring de `firmas/ecg_mortara.py`).

"ECOCARDIOGRAMA DOPPLER" se conserva NO VERIFICADO contra ninguna muestra
real: `tests/fixtures/v1/documentos.py::texto_eco` y varios tests de
integración (`test_e2e_linkage`, `test_procesar_carpeta`, etc.) lo usan como
único encabezado del layout sintético legado. Sacarlo rompería esos
fixtures sin necesidad -- no hace daño dejarlo (`Firma.puntaje` ya no
depende de un solo marcador para decidir, ver `firmas/base.py` y
`detector_tipo.py`). "FRACCION DE ACORTAMIENTO" SÍ se saca: no aparece en el
documento real, no la usa ningún fixture del repo, y el campo real es "FA"
(dos letras, demasiado genérico para ser marcador de firma sin colisionar).

"S.C." se conserva: 4 caracteres, sí aparece en el documento real ("S.C.
2,42 m2"), y no colisiona con ningún marcador de laboratorio ni de ECG en
los fixtures del repo (verificado). Por sí solo ya no alcanza para
reconocer el tipo -- ver `Firma.puntaje` y `detectar_tipo`, que exigen la
firma con más evidencia total, no la primera que matchea.

Marcadores agregados, verificados contra el texto real: "SERVICIO DE
ECOCARDIOGRAFIA", "ECOGRAFIA DOPPLER COLOR CARDIACA", "EVALUACION DE FLUJOS
POR DOPPLER" y "DOPPLER TISULAR". Los tres primeros ya los usa
`tests/fixtures/pdf_sintetico.py` para el layout sintético vigente, así que
además de reflejar el documento real no rompen ese fixture.
"""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento

from .base import Firma

FIRMA = Firma(
    tipo=TipoDocumento.ECOCARDIOGRAMA,
    marcadores=(
        "SERVICIO DE ECOCARDIOGRAFIA",
        "ECOGRAFIA DOPPLER COLOR CARDIACA",
        "EVALUACION DE FLUJOS POR DOPPLER",
        "DOPPLER TISULAR",
        "ECOCARDIOGRAMA DOPPLER",
        "S.C.",
    ),
)
