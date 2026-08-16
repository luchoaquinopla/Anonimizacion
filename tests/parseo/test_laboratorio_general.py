"""Tests del parser de laboratorio general (spec: document-parsing).

Ver requirement "Parser de laboratorio con reconciliación multi-página":
header repetido en cada página + secciones repartidas entre páginas deben
reconciliarse en un único registro por Nº de Petición.
"""

from __future__ import annotations

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.laboratorio_general import ParseadorLaboratorioGeneral

_HEADER = (
    "Apellido y Nombre: Perez Juan\n"
    "DNI: 30111222\n"
    "F.Nacimiento: 01/05/1980\n"
    "Edad: 44\n"
    "Medico derivante: Dr. Gomez\n"
    "Nº Petición: 987654\n"
    "Fecha: 10/01/2024\n"
    "Hora Extracción: 08:30\n"
    "Origen: Guardia\n"
)


def test_parsea_documento_de_laboratorio_de_4_paginas_en_un_solo_registro() -> None:
    paginas = (
        _HEADER + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",
        _HEADER + "HEMOSTASIA\nTP | 12 | seg | 10-14\n",
        _HEADER + "QUIMICA CLINICA\nGlucosa | 90 | mg/dL | 70-100\n",
        _HEADER + "IONOGRAMA\nSodio | 140 | mEq/L | 135-145\n",
    )
    texto = TextoExtraido(paginas=paginas)

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    assert resultado.tipo_documento is TipoDocumento.LABORATORIO
    assert resultado.contenido.numero_peticion == "987654"
    secciones = {r.seccion for r in resultado.contenido.resultados}
    assert secciones == {"HEMATOLOGIA", "HEMOSTASIA", "QUIMICA CLINICA", "IONOGRAMA"}
    assert len(resultado.contenido.resultados) == 4


def test_reconcilia_header_repetido_en_una_sola_identidad() -> None:
    paginas = (_HEADER + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",) * 2
    texto = TextoExtraido(paginas=paginas)

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    assert resultado.identidad.nombre.get_secret_value() == "Perez Juan"
    assert resultado.fecha_estudio.isoformat() == "2024-01-10"


def test_tolera_seccion_ausente() -> None:
    texto = TextoExtraido(
        paginas=(_HEADER + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",)
    )
    resultado = ParseadorLaboratorioGeneral().parsear(texto)
    assert len(resultado.contenido.resultados) == 1


def test_numero_peticion_inconsistente_entre_paginas_lanza_error_parseo() -> None:
    pagina_1 = _HEADER + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n"
    pagina_2 = pagina_1.replace("987654", "111111")
    texto = TextoExtraido(paginas=(pagina_1, pagina_2))

    with pytest.raises(ErrorParseo) as info:
        ParseadorLaboratorioGeneral().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO


def test_header_ausente_lanza_error_parseo() -> None:
    texto = TextoExtraido(paginas=("HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",))
    with pytest.raises(ErrorParseo) as info:
        ParseadorLaboratorioGeneral().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO
