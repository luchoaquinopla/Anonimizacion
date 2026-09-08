"""Tests del generador de esqueletos de formato.

Tarea "herramienta de esqueleto de formato": convierte un PDF real (que el
operador tiene en su máquina, nunca en el repo) en un fixture de texto
versionable sin PII. Diseño ALLOWLIST, no denylist -- ver `esqueleto.py`:
todo token se enmascara por forma salvo que esté en la allowlist estructural
explícita que el propio código ya conoce (marcadores de firma, etiquetas de
header, unidades). La propiedad vale por CONSTRUCCIÓN, no por calidad de
detección -- por eso el centinela de abajo es el más importante de esta
tarea: si se rompe, se filtran datos de pacientes reales a un repositorio
de git.
"""

from __future__ import annotations

import re
from datetime import datetime

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.esqueleto import (
    ALLOWLIST_ESTRUCTURAL,
    enmascarar_por_forma,
    generar_esqueleto,
    generar_fixture_parseable,
)
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido


def test_enmascara_letras_y_digitos_preservando_longitud_y_separadores() -> None:
    original = "Perez Juan, DNI 30111222, nacio el 01/05/1980"

    resultado = enmascarar_por_forma(original)

    assert len(resultado) == len(original)
    assert resultado.count(",") == original.count(",")
    assert resultado.count("/") == original.count("/")
    assert resultado.count(" ") == original.count(" ")
    assert "Perez" not in resultado
    assert "30111222" not in resultado


def test_enmascara_letras_a_x_y_digitos_a_cero_preservando_forma() -> None:
    resultado = enmascarar_por_forma("Ana01")

    assert resultado == "XXX00"


def test_no_enmascara_las_etiquetas_estructurales_conocidas() -> None:
    original = "Apellido y Nombre: Perez Juan\nDNI: 30111222\n"

    resultado = enmascarar_por_forma(original)

    assert "Apellido y Nombre:" in resultado
    assert "DNI:" in resultado
    assert "Perez Juan" not in resultado
    assert "30111222" not in resultado


def test_no_enmascara_marcadores_de_firma_conocidos() -> None:
    original = "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n"

    resultado = enmascarar_por_forma(original)

    assert "HEMATOLOGIA" in resultado
    assert "Hemoglobina" not in resultado


def test_etiqueta_no_enmascara_substring_dentro_de_un_nombre_real() -> None:
    """La allowlist usa límites de palabra: "Hora" (etiqueta de laboratorio)
    NO debe dejar un fragmento de un nombre real como "Horacio" sin
    enmascarar."""
    resultado = enmascarar_por_forma("Horacio Perez")

    assert "Hora" not in resultado
    assert "Horacio" not in resultado


def test_centinela_nombre_dni_y_fecha_nacimiento_nunca_aparecen_en_el_esqueleto() -> None:
    """EL CENTINELA MÁS IMPORTANTE de esta tarea: si esto falla, se filtran
    datos de pacientes reales a un repositorio de git."""
    nombre = "Fernandez Marta Beatriz"
    dni = "28999111"
    fecha_nacimiento = "15/03/1962"
    texto_pagina = (
        f"Apellido y Nombre: {nombre}\n"
        f"DNI: {dni}\n"
        f"F.Nacimiento: {fecha_nacimiento}\n"
        "Nº Petición: 987654\n"
        "Fecha: 10/01/2024\n"
        "HEMATOLOGIA\nHemoglobina | 14.5 | g/dL | 12.0-16.0\n"
    )
    texto = TextoExtraido(paginas=(texto_pagina,), paginas_ordenadas=(texto_pagina,))

    esqueleto = generar_esqueleto(texto)

    for representacion in (esqueleto.paginas, esqueleto.paginas_ordenadas):
        for pagina in representacion:
            assert nombre not in pagina
            assert dni not in pagina
            assert fecha_nacimiento not in pagina
            for parte in nombre.split():
                assert parte not in pagina


def test_preserva_longitudes_y_posiciones_por_pagina() -> None:
    """El esqueleto debe servir para detectar que una etiqueta se movió:
    longitudes y posiciones de las etiquetas se preservan exactamente."""
    texto_pagina = "Apellido y Nombre: Perez Juan\nDNI: 30111222\n"
    texto = TextoExtraido(paginas=(texto_pagina,), paginas_ordenadas=(texto_pagina,))

    esqueleto = generar_esqueleto(texto)

    assert len(esqueleto.paginas[0]) == len(texto_pagina)
    assert len(esqueleto.paginas_ordenadas[0]) == len(texto_pagina)
    assert esqueleto.paginas[0].index("DNI:") == texto_pagina.index("DNI:")
    assert esqueleto.paginas[0].count("\n") == texto_pagina.count("\n")


def test_conserva_ambas_representaciones_paginas_y_paginas_ordenadas() -> None:
    """Un esqueleto que no reproduzca ambas representaciones no sirve para
    calibrar el ECG, que usa la de orden de dibujado (`paginas`)."""
    pagina_dibujado = "MORTARA\nID:900321  05-JUN-2025  10:22:31\nPrueba Sintetica~,\n"
    pagina_ordenada = "MORTARA\nPrueba Sintetica~,  ID:900321  05-JUN-2025  10:22:31\n"
    texto = TextoExtraido(paginas=(pagina_dibujado,), paginas_ordenadas=(pagina_ordenada,))

    esqueleto = generar_esqueleto(texto)

    assert len(esqueleto.paginas) == 1
    assert len(esqueleto.paginas_ordenadas) == 1
    assert esqueleto.paginas[0] != esqueleto.paginas_ordenadas[0]
    assert "Prueba Sintetica" not in esqueleto.paginas[0]
    assert "Prueba Sintetica" not in esqueleto.paginas_ordenadas[0]


def test_detecta_tipo_y_reporta_puntaje_de_la_firma() -> None:
    texto_pagina = "HEMATOLOGIA\nHEMOSTASIA\nQUIMICA CLINICA\nApellido y Nombre: Perez Juan\n"
    texto = TextoExtraido(paginas=(texto_pagina,), paginas_ordenadas=(texto_pagina,))

    esqueleto = generar_esqueleto(texto)

    assert esqueleto.tipo_detectado is TipoDocumento.LABORATORIO
    assert esqueleto.puntaje == 3
    assert esqueleto.total_marcadores == 5


def test_tipo_no_reconocido_reporta_puntaje_cero() -> None:
    texto = TextoExtraido(paginas=("solo texto sin ningun marcador conocido",))

    esqueleto = generar_esqueleto(texto)

    assert esqueleto.tipo_detectado is TipoDocumento.TIPO_NO_RECONOCIDO
    assert esqueleto.puntaje == 0


def test_allowlist_estructural_no_esta_vacia_y_se_deriva_de_constantes_del_codigo() -> None:
    assert len(ALLOWLIST_ESTRUCTURAL) > 10
    assert "HEMATOLOGIA" in ALLOWLIST_ESTRUCTURAL
    assert any("DNI" in etiqueta for etiqueta in ALLOWLIST_ESTRUCTURAL)


def test_formatear_incluye_tipo_puntaje_y_ambas_representaciones() -> None:
    texto_pagina = "HEMATOLOGIA\nHEMOSTASIA\nQUIMICA CLINICA\nApellido y Nombre: Perez Juan\n"
    texto = TextoExtraido(paginas=(texto_pagina,), paginas_ordenadas=(texto_pagina,))

    esqueleto = generar_esqueleto(texto)
    formateado = esqueleto.formatear()

    assert "laboratorio" in formateado
    assert "3/5" in formateado
    assert "Perez Juan" not in formateado
    assert "orden de dibujado" in formateado
    assert "orden geometrico" in formateado


# ---------------------------------------------------------------------------
# Fixture PARSEABLE (Tarea "fixture parseable de esqueletos reales") -- ver
# el segundo bloque de docstring de `esqueleto.py`. Texto sintético con el
# layout real de laboratorio (separadores de 2+ espacios que `_primer_segmento`
# de `parseo/laboratorio_general.py` espera) para poder ejercer la coherencia
# de fechas sin depender de un PDF real.
# ---------------------------------------------------------------------------

_PAGINA_LAB_SINTETICA = (
    "Apellido y Nombre: Fernandez Marta                          Fecha:  10/01/2024\n"
    "F.Nacimiento :  15/03/1962                                              Nº Petición: 987654\n"
    "Edad: 61                DNI:  28999111                               Hora de Extracción:  08:15\n"
    "Médico: Gomez Ana                                                       Origen: Guardia\n"
    "HEMATOLOGIA\n"
    "Hemoglobina | 14.5 | g/dL | 12.0-16.0\n"
)


def _texto_lab_sintetico() -> TextoExtraido:
    return TextoExtraido(paginas=(_PAGINA_LAB_SINTETICA,), paginas_ordenadas=(_PAGINA_LAB_SINTETICA,))


def test_fixture_parseable_es_deterministico() -> None:
    """Mismo input -> mismo sustituto, siempre -- requisito duro (ver
    docstring de `esqueleto.py`): `parseo/laboratorio_general.py` exige que
    el Nº de Petición no cambie entre páginas del mismo documento."""
    texto = _texto_lab_sintetico()

    primera_corrida = generar_fixture_parseable(texto).formatear()
    segunda_corrida = generar_fixture_parseable(texto).formatear()

    assert primera_corrida == segunda_corrida


def test_fixture_parseable_nunca_deja_el_valor_original_verbatim() -> None:
    """Mismo espíritu que el centinela más importante del esqueleto
    enmascarado (`test_centinela_nombre_dni_y_fecha_nacimiento_nunca_aparecen_en_el_esqueleto`),
    aplicado al fixture PARSEABLE -- acá el riesgo es mayor: hay contenido
    con forma de dato real, no `X`/`0`."""
    texto = _texto_lab_sintetico()

    fixture = generar_fixture_parseable(texto)

    for pagina in fixture.paginas + fixture.paginas_ordenadas:
        assert "Fernandez Marta" not in pagina
        assert "28999111" not in pagina
        assert "15/03/1962" not in pagina
        assert "987654" not in pagina


def test_fixture_parseable_no_enmascara_las_etiquetas_estructurales_conocidas() -> None:
    texto = _texto_lab_sintetico()

    fixture = generar_fixture_parseable(texto)
    pagina = fixture.paginas[0]

    for etiqueta in (
        "Apellido y Nombre:",
        "F.Nacimiento :",
        "Nº Petición:",
        "Edad:",
        "DNI:",
        "Hora de Extracción:",
        "Médico:",
        "Origen:",
        "Fecha:",
        "HEMATOLOGIA",
    ):
        assert etiqueta in pagina


def test_fixture_parseable_preserva_forma_de_letras_y_digitos() -> None:
    texto = _texto_lab_sintetico()

    pagina = generar_fixture_parseable(texto).paginas[0]

    # El nombre sustituto tiene la misma cantidad de palabras y la misma
    # longitud carácter a carácter que "Fernandez Marta".
    coincidencia = re.search(r"Apellido y Nombre: (\S+) (\S+)", pagina)
    assert coincidencia is not None
    assert len(coincidencia.group(1)) == len("Fernandez")
    assert len(coincidencia.group(2)) == len("Marta")
    assert coincidencia.group(1)[0].isupper()  # preserva mayus/minus caracter a caracter
    # El DNI sustituto tiene la misma cantidad de dígitos que el original.
    coincidencia_dni = re.search(r"DNI:\s*(\d+)", pagina)
    assert coincidencia_dni is not None
    assert len(coincidencia_dni.group(1)) == len("28999111")


def test_fixture_parseable_sustituye_fechas_por_fechas_validas_y_coherentes() -> None:
    """Fecha de nacimiento < fecha de estudio, y la edad sintética coincide
    con la diferencia de años entre ambas -- ver docstring de `esqueleto.py`
    sobre por qué esto no es cosmético (`_fecha_sintetica`/`_edad_sintetica`)."""
    texto = _texto_lab_sintetico()

    pagina = generar_fixture_parseable(texto).paginas_ordenadas[0]

    fecha_estudio = datetime.strptime(re.search(r"Fecha:\s*(\d{2}/\d{2}/\d{4})", pagina).group(1), "%d/%m/%Y").date()
    fecha_nac = datetime.strptime(
        re.search(r"F\.Nacimiento :\s*(\d{2}/\d{2}/\d{4})", pagina).group(1), "%d/%m/%Y"
    ).date()
    edad = int(re.search(r"Edad:\s*(\d+)", pagina).group(1))

    assert fecha_nac < fecha_estudio
    assert fecha_estudio.replace(year=fecha_estudio.year - edad) == fecha_nac


def test_fixture_parseable_conserva_ambas_representaciones() -> None:
    pagina_dibujado = (
        "Apellido y Nombre: Fernandez Marta      Fecha:  10/01/2024\nF.Nacimiento :  15/03/1962\n"
    )
    pagina_ordenada = "Apellido y Nombre: Fernandez Marta                     Fecha:  10/01/2024\n"
    texto = TextoExtraido(paginas=(pagina_dibujado,), paginas_ordenadas=(pagina_ordenada,))

    fixture = generar_fixture_parseable(texto)

    assert len(fixture.paginas) == 1
    assert len(fixture.paginas_ordenadas) == 1
    assert "Fernandez Marta" not in fixture.paginas[0]
    assert "Fernandez Marta" not in fixture.paginas_ordenadas[0]


def test_formatear_fixture_parseable_incluye_advertencia_tipo_y_ambas_representaciones() -> None:
    texto = _texto_lab_sintetico()

    formateado = generar_fixture_parseable(texto).formatear()

    assert "laboratorio" in formateado
    assert "SINTETICOS" in formateado
    assert "Fernandez Marta" not in formateado
    assert "orden de dibujado" in formateado
    assert "orden geometrico" in formateado
