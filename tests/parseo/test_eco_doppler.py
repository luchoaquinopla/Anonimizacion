"""Tests del parser de ecocardiograma Doppler (spec: document-parsing).

Ver requirement "Parser de ecocardiograma": header + medidas estructuradas +
texto libre por sección + firma del médico informante, todo en un mismo
`DocumentoParseado`.
"""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler

_DOCUMENTO_COMPLETO = (
    "Paciente: Fernandez Marta\n"
    "Documento: 28999111\n"
    "Nº Estudio: EE-2024-01\n"
    "Fecha: 20/03/2024\n"
    "Medico Solicitante: Dr. Ruiz\n"
    "Peso: 68\n"
    "Altura: 165\n"
    "S.C.: 1.75\n"
    "\n"
    "MEDIDAS\n"
    "AO | 28 | mm\n"
    "AI | 32 | mm\n"
    "DDVI | 48 | mm\n"
    "DSVI | 30 | mm\n"
    "FA | 35 | %\n"
    "Septum | 9 | mm\n"
    "P. Posterior | 9 | mm\n"
    "\n"
    "MOTILIDAD SEGMENTARIA\n"
    "Motilidad conservada en todos los segmentos.\n"
    "\n"
    "VALVULAS\n"
    "Valvulas de aspecto y funcion normal.\n"
    "\n"
    "PERICARDIO\n"
    "Sin derrame pericardico.\n"
    "\n"
    "FLUJOS DOPPLER\n"
    "Flujos dentro de parametros normales.\n"
    "\n"
    "CONCLUSIONES\n"
    "Estudio dentro de limites normales.\n"
    "\n"
    "Firma: Dr. Carlos Fernandez - MP 12345\n"
)


def test_parsea_ecocardiograma_completo() -> None:
    texto = TextoExtraido(paginas=(_DOCUMENTO_COMPLETO,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    assert resultado.tipo_documento is TipoDocumento.ECOCARDIOGRAMA
    assert resultado.identidad.nombre.get_secret_value() == "Fernandez Marta"
    assert len(resultado.contenido.medidas) == 7
    nombres_medidas = {m.nombre for m in resultado.contenido.medidas}
    assert "AO" in nombres_medidas
    assert len(resultado.contenido.secciones_texto) == 5
    assert resultado.contenido.firma is not None
    assert resultado.contenido.firma.nombre == "Dr. Carlos Fernandez"
    assert resultado.contenido.firma.matricula == "12345"


def test_secciones_de_texto_no_se_mezclan_con_medidas() -> None:
    texto = TextoExtraido(paginas=(_DOCUMENTO_COMPLETO,))
    resultado = ParseadorEcoDoppler().parsear(texto)
    seccion_valvulas = next(
        s for s in resultado.contenido.secciones_texto if s.nombre == "VALVULAS"
    )
    assert "normal" in seccion_valvulas.texto.lower()


def test_header_ausente_lanza_error_parseo() -> None:
    texto = TextoExtraido(paginas=("MEDIDAS\nAO | 28 | mm\n",))
    with pytest.raises(ErrorParseo) as info:
        ParseadorEcoDoppler().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO


def test_usa_paginas_ordenadas_y_trunca_campos_que_comparten_linea_visual() -> None:
    """Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
    "Fix: extracción con sort=True + firmas ECG reales"): mismo fix que
    `laboratorio_general.py` -- lee `paginas_ordenadas` y trunca en el
    separador de 2+ espacios para no arrastrar el campo vecino de la misma
    fila visual.
    """
    pagina_sin_ordenar = "Paciente:\nFecha:\nMEDIDAS\nAO | 28 | mm\nFernandez Marta\n20/03/2024\n"
    pagina_ordenada = (
        "Paciente: Fernandez Marta      Fecha: 20/03/2024\n"
        "MEDIDAS\nAO | 28 | mm\n"
    )
    texto = TextoExtraido(paginas=(pagina_sin_ordenar,), paginas_ordenadas=(pagina_ordenada,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    assert resultado.identidad.nombre.get_secret_value() == "Fernandez Marta"
    assert resultado.fecha_estudio.isoformat() == "2024-03-20"
