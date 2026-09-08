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

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.esqueleto import ALLOWLIST_ESTRUCTURAL, enmascarar_por_forma, generar_esqueleto
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
