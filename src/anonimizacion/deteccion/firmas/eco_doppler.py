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

"ECOCARDIOGRAMA DOPPLER" y "FRACCION DE ACORTAMIENTO" se RETIRARON (tarea
"regenerar corpus sintético desde layouts reales"): ninguno de los dos
aparece en el documento real -- verificado contra
`tests/fixtures/esqueletos/eco-01.txt` y
`tests/fixtures/parseables/eco-01.txt`, ambos derivados de un PDF real del
Instituto de Cardiología de Corrientes (ver `esqueleto.py`). El único motivo
por el que "ECOCARDIOGRAMA DOPPLER" seguía vivo era que
`tests/fixtures/v1/documentos.py::texto_eco` lo usaba como único encabezado
del layout sintético legado; ese fixture ahora genera el layout real
(mismos marcadores que `tests/fixtures/pdf_sintetico.py`), así que el
marcador fantasma ya no tiene ningún consumidor. Ver
`tests/deteccion/test_centinela_esqueletos.py` y
`tests/fixtures/test_pdf_sintetico_corpus.py::
test_corpus_sintetico_no_declara_marcadores_no_verificados_contra_lo_real`
para la prueba de que se puede retirar sin romper nada.

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
        "S.C.",
    ),
)
