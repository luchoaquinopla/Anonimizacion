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


def test_conserva_la_pagina_real_de_resultados_repetidos() -> None:
    paginas = (
        _HEADER + "HEMATOLOGIA\nGlucosa | 90 | mg/dL | 70-100\n",
        _HEADER + "QUIMICA CLINICA\nGlucosa | 90 | mg/dL | 70-100\n",
    )

    documento = ParseadorLaboratorioGeneral().parsear(TextoExtraido(paginas))

    assert [fuente.pagina for fuente in documento.fuentes] == [1, 2]


def test_numero_peticion_inconsistente_entre_paginas_lanza_error_parseo() -> None:
    pagina_1 = _HEADER + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n"
    pagina_2 = pagina_1.replace("987654", "111111")
    texto = TextoExtraido(paginas=(pagina_1, pagina_2))

    with pytest.raises(ErrorParseo) as info:
        ParseadorLaboratorioGeneral().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO


def test_fecha_nacimiento_se_normaliza_a_iso_8601() -> None:
    """Fix post-PR9: `fecha_nac` se normaliza a ISO para que el puente
    `id_alt_paciente` (`pseudonimizacion/claves.py`) coincida con el ECG,
    que usa un formato de fecha distinto (`DD-MON-YYYY`, ver
    `parseo/ecg_mortara.py`).
    """
    texto = TextoExtraido(paginas=(_HEADER + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",))
    resultado = ParseadorLaboratorioGeneral().parsear(texto)
    assert resultado.identidad.fecha_nac.get_secret_value() == "1980-05-01"


def test_fecha_nacimiento_no_parseable_queda_en_none_sin_romper_el_parseo() -> None:
    header_fecha_nac_invalida = _HEADER.replace("F.Nacimiento: 01/05/1980", "F.Nacimiento: no-disponible")
    texto = TextoExtraido(
        paginas=(header_fecha_nac_invalida + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",)
    )
    resultado = ParseadorLaboratorioGeneral().parsear(texto)
    assert resultado.identidad.fecha_nac is None


def test_header_ausente_lanza_error_parseo() -> None:
    texto = TextoExtraido(paginas=("HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",))
    with pytest.raises(ErrorParseo) as info:
        ParseadorLaboratorioGeneral().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO


def test_header_real_con_espacio_antes_de_dos_puntos_y_etiquetas_alternativas() -> None:
    """Fix post-PR9 #4 (recalibración lab/eco contra 3 documentos reales):
    el documento real trae `F.Nacimiento :` (espacio antes de los dos
    puntos), `Médico:` (sin la palabra "derivante") y `Hora de Extracción:`
    (con la palabra "de" en el medio). Sin este fix, `fecha_nac` nunca se
    captura y el puente `id_alt_paciente` hacia el ECG nunca se arma.
    """
    header_real = (
        "Apellido y Nombre: Perez Juan\n"
        "DNI: 30111222\n"
        "F.Nacimiento : 01/05/1980\n"
        "Edad: 44\n"
        "Médico: Dr. Gomez\n"
        "Nº Petición: 987654\n"
        "Fecha: 10/01/2024\n"
        "Hora de Extracción: 08:30\n"
        "Origen: Guardia\n"
    )
    texto = TextoExtraido(
        paginas=(header_real + "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n",)
    )

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    assert resultado.identidad.fecha_nac.get_secret_value() == "1980-05-01"
    assert resultado.adicionales["medico_derivante"] == "Dr. Gomez"
    assert resultado.adicionales["hora_extraccion"] == "08:30"


def test_cuerpo_real_espaciado_sin_pipes_extrae_filas_con_seccion_y_subseccion() -> None:
    """Fix post-PR9 #6 (cuerpo real de laboratorio, ver
    `sdd/pdf-pii-anonymization/apply-progress`): el documento real NO usa
    `|` como separador -- las columnas van separadas por 2+ espacios, la
    sección aparece dos veces ("-NOMBRE-" y luego "NOMBRE" sin guiones), hay
    sub-bloques (p. ej. "SUBBLOQUE" dentro de la sección) que también deben
    marcar `seccion` para las filas siguientes, y hay ruido (encabezado de
    columna repetido, número de página, notas con ":") que no debe romper
    el parseo ni generar filas espurias. Todos los valores son inventados.
    """
    cuerpo = (
        "        Pruebas               Resultado   Fecha y Resultado     Unidades              Valores de Referencia\n"
        "                                   Actual           Anterior\n"
        "\n"
        "                                   -HEMATOLOGIA-\n"
        "\n"
        "HEMATOLOGIA\n"
        "PruebaUno                   11                          unidadx                  0 - 20\n"
        "\n"
        "SUBBLOQUE\n"
        "\n"
        "PruebaDos                         22                  unidady                    10 - 30\n"
        "\n"
        "PruebaTres                                    33.5\n"
        "                                                                                                         Nota: texto\n"
        "                                                                                             explicativo largo que\n"
        "                                                                                                           no es una fila.\n"
        "1  de  3\n"
    )
    texto = TextoExtraido(paginas=(_HEADER + cuerpo,))

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    filas = {r.prueba: r for r in resultado.contenido.resultados}
    assert set(filas) == {"PruebaUno", "PruebaDos", "PruebaTres"}
    assert filas["PruebaUno"].seccion == "HEMATOLOGIA"
    assert filas["PruebaUno"].resultado == "11"
    assert filas["PruebaUno"].unidades == "unidadx"
    assert filas["PruebaUno"].valores_referencia == "0 - 20"
    assert filas["PruebaDos"].seccion == "SUBBLOQUE"
    assert filas["PruebaDos"].unidades == "unidady"
    assert filas["PruebaDos"].valores_referencia == "10 - 30"
    assert filas["PruebaTres"].seccion == "SUBBLOQUE"
    assert filas["PruebaTres"].resultado == "33.5"
    assert filas["PruebaTres"].unidades is None
    assert filas["PruebaTres"].valores_referencia is None


def test_cuerpo_real_acepta_resultado_cualitativo_estructurado_sin_absorber_narrativa() -> None:
    cuerpo = (
        "HEMATOLOGIA\n"
        "Marcador Cualitativo  NO DETECTADO\n"
        "Comentario general  Texto narrativo que no es un resultado\n"
    )

    resultado = ParseadorLaboratorioGeneral().parsear(TextoExtraido(paginas=(_HEADER + cuerpo,)))

    assert [(fila.prueba, fila.resultado) for fila in resultado.contenido.resultados] == [
        ("Marcador Cualitativo", "NO DETECTADO")
    ]


def test_canonicaliza_ionograma_serico_y_conserva_pagina_y_ordinal() -> None:
    texto = TextoExtraido(
        paginas=(
            _HEADER + "HEMATOLOGIA\nMarcador Cualitativo  REACTIVO\n",
            "IONOGRAMA SERICO\nSodio  140  mEq/L  135 - 145\n",
        )
    )

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    assert [fila.seccion for fila in resultado.contenido.resultados] == ["HEMATOLOGIA", "IONOGRAMA"]
    assert [(fuente.pagina, fuente.ordinal) for fuente in resultado.fuentes] == [(1, 0), (2, 1)]


def test_conserva_seccion_para_resultados_que_continuan_en_la_pagina_siguiente() -> None:
    texto = TextoExtraido(
        paginas=(
            _HEADER + "HEMATOLOGIA\nFORMULA LEUCOCITARIA\nNeutrofilos  55\n",
            "Nº Petición: 987654\nMonocitos  REACTIVO\nHEMOSTASIA\nRIN  1\n",
        )
    )

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    assert [(fila.seccion, fila.prueba) for fila in resultado.contenido.resultados] == [
        ("FORMULA LEUCOCITARIA", "Neutrofilos"),
        ("FORMULA LEUCOCITARIA", "Monocitos"),
        ("HEMOSTASIA", "RIN"),
    ]
    assert [(fuente.pagina, fuente.ordinal) for fuente in resultado.fuentes] == [(1, 0), (2, 1), (2, 2)]


def test_nombre_de_prueba_partido_en_dos_lineas_por_parentesis_se_reconstruye() -> None:
    """Fix post-merge (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
    "Fix: persistencia del puente id_alt_paciente en Postgres entre
    corridas" -- gap conocido documentado en Fix#6, ahora resuelto): en el
    documento real, un nombre de prueba largo queda partido en DOS líneas
    cuando no entra en una sola línea del PDF -- la primera línea trae el
    inicio del nombre + un paréntesis SIN cerrar + el valor + la unidad; la
    segunda línea, corta, trae solo el cierre del paréntesis + el resto del
    nombre. Todos los valores son inventados.
    """
    cuerpo = (
        "HEMATOLOGIA\n"
        "Prueba Muy Larga Con Nombre (ALGO-EXTRA    102                         unidad/rara\n"
        " 2021)\n"
        "PruebaSiguiente                   15                  unidadz                    1 - 5\n"
    )
    texto = TextoExtraido(paginas=(_HEADER + cuerpo,))

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    filas = {r.prueba: r for r in resultado.contenido.resultados}
    assert "Prueba Muy Larga Con Nombre (ALGO-EXTRA 2021)" in filas
    fila = filas["Prueba Muy Larga Con Nombre (ALGO-EXTRA 2021)"]
    assert fila.resultado == "102"
    assert fila.unidades == "unidad/rara"
    assert fila.seccion == "HEMATOLOGIA"
    # la fila siguiente no se pierde ni se corrompe por la reconstrucción del nombre partido
    assert "PruebaSiguiente" in filas
    assert filas["PruebaSiguiente"].resultado == "15"
    assert filas["PruebaSiguiente"].valores_referencia == "1 - 5"


def test_nombre_de_prueba_con_parentesis_balanceado_no_dispara_reconstruccion() -> None:
    """Caso negativo: un nombre de prueba con paréntesis YA balanceado en una
    sola línea no debe intentar fusionarse con la línea siguiente (evita
    falsos positivos del fix anterior)."""
    cuerpo = (
        "HEMATOLOGIA\n"
        "Prueba Con Parentesis (OK)    50                         unidadw\n"
        "PruebaSiguiente                   15                  unidadz                    1 - 5\n"
    )
    texto = TextoExtraido(paginas=(_HEADER + cuerpo,))

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    filas = {r.prueba: r for r in resultado.contenido.resultados}
    assert "Prueba Con Parentesis (OK)" in filas
    assert filas["Prueba Con Parentesis (OK)"].resultado == "50"
    assert "PruebaSiguiente" in filas
    assert filas["PruebaSiguiente"].resultado == "15"


def test_usa_paginas_ordenadas_y_trunca_campos_que_comparten_linea_visual() -> None:
    """Fix post-PR9: el parser lee `paginas_ordenadas` (orden geométrico,
    `sort=True`), no `paginas` (orden de dibujado) -- ver
    `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix: extracción con
    sort=True". Contra el PDF real, dos campos pueden compartir la misma
    fila visual (columna izquierda + columna derecha): sin truncar en el
    separador de columnas (2+ espacios, misma convención que
    `parseo/ecg_mortara.py::_primer_segmento`), el regex `.+` de "Apellido y
    Nombre:" capturaría también " Fecha: 10/01/2024" como parte del nombre.
    """
    pagina_sin_ordenar = (
        "Apellido y Nombre:\nFecha:\nNº Petición:\nEdad:\nHEMATOLOGIA\n"
        "Hemoglobina | 14.5 | g/dL | 12.0-16.0\nPerez Juan\n10/01/2024\n987654\n44\n"
    )
    pagina_ordenada = (
        "Apellido y Nombre: Perez Juan      Fecha: 10/01/2024\n"
        "Nº Petición: 987654      Edad: 44\n"
        "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n"
    )
    texto = TextoExtraido(paginas=(pagina_sin_ordenar,), paginas_ordenadas=(pagina_ordenada,))

    resultado = ParseadorLaboratorioGeneral().parsear(texto)

    assert resultado.identidad.nombre.get_secret_value() == "Perez Juan"
    assert resultado.fecha_estudio.isoformat() == "2024-01-10"
