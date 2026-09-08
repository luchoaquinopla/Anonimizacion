"""Tests del parser de ecocardiograma Doppler (spec: document-parsing).

Ver requirement "Parser de ecocardiograma": header + medidas estructuradas +
texto libre por sección + firma del médico informante, todo en un mismo
`DocumentoParseado`.
"""

from __future__ import annotations

from datetime import time

import pytest

from anonimizacion.dominio.errores import CodigoErrorDocumento, DetalleParseoIncompleto, ErrorParseo
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler

_DOCUMENTO_COMPLETO = (
    "Paciente: Fernandez Marta\n"
    "Documento: 28999111\n"
    "Nº Estudio: EE-2024-01\n"
    "Fecha Estudio: 20/03/2024\n"
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
    "VALVULAS CARDIACAS\n"
    "Valvulas de aspecto y funcion normal.\n"
    "\n"
    "PERICARDIO\n"
    "Sin derrame pericardico.\n"
    "\n"
    "EVALUACION DE FLUJOS POR DOPPLER\n"
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
        s for s in resultado.contenido.secciones_texto if s.nombre == "VALVULAS CARDIACAS"
    )
    assert "normal" in seccion_valvulas.texto.lower()


def test_conserva_paginas_reales_de_medida_seccion_y_firma_repetidas() -> None:
    paginas = (
        "Paciente: Persona Sintetica\nFecha Estudio: 20/03/2024\nMEDIDAS\nAO | 28 | mm\nCONCLUSIONES\nTexto repetido.\nFirma: Medico Uno - MP 1",
        "MEDIDAS\nAI | 28 | mm\nPERICARDIO\nTexto repetido.\nFirma: Medico Dos - MP 2",
    )

    documento = ParseadorEcoDoppler().parsear(TextoExtraido(paginas))

    fuentes = {(fuente.id_campo, fuente.ordinal): fuente.pagina for fuente in documento.fuentes}
    assert fuentes[("eco.medida", 0)] == 1
    assert fuentes[("eco.medida", 1)] == 2
    assert fuentes[("eco.seccion", 0)] == 1
    assert fuentes[("eco.seccion", 1)] == 2
    assert fuentes[("eco.firma", 0)] == 2


def test_conserva_subseccion_con_padre_y_la_reconciliacion_la_ancla() -> None:
    from anonimizacion.reconciliacion.eco_doppler import ReconciliadorEcoDoppler

    texto = TextoExtraido((
        "Paciente: Persona Sintetica\nFecha Estudio: 20/03/2024\nVALVULAS CARDIACAS\nAORTICA\nSin estenosis.",
    ))
    documento = ParseadorEcoDoppler().parsear(texto)

    assert documento.contenido.secciones_texto[0].nombre == "VALVULAS CARDIACAS - AORTICA"
    ReconciliadorEcoDoppler().reconciliar(documento, texto)


def test_seccion_que_cruza_paginas_conserva_la_pagina_de_inicio() -> None:
    texto = TextoExtraido((
        "Paciente: Persona Sintetica\nFecha Estudio: 20/03/2024\nCONCLUSIONES\nTexto de la primera pagina.",
        "PERICARDIO\nSin derrame.",
    ))

    documento = ParseadorEcoDoppler().parsear(texto)

    fuentes_seccion = [fuente for fuente in documento.fuentes if fuente.id_campo == "eco.seccion"]
    assert [(fuente.ordinal, fuente.pagina) for fuente in fuentes_seccion] == [(0, 1), (1, 2)]


def test_seccion_que_cruza_paginas_excluye_encabezado_y_pie_repetidos() -> None:
    from anonimizacion.reconciliacion.eco_doppler import ReconciliadorEcoDoppler

    texto = TextoExtraido((
        _HEADER_MINIMO
        + "Nº Estudio: 900\n"
        + "EVALUACION DE FLUJOS POR DOPPLER\n"
        + "FLUJO PULMONAR\n"
        + "Informe no valido sin firma\nPagina 1 de 2\n",
        "SERVICIO DE ECOCARDIOGRAFIA\n"
        + "Paciente: Prueba Sintetica  Documento: 11222333  Fecha Estudio: 05/06/2025\n"
        + "Edad: 50 anos  Nº Estudio: 900  Peso: 70 kg  Altura: 170 cm  S.C.: 1.8 m2\n"
        + "Medico Solicitante: Profesional Sintetico\n"
        + "Flujo sistolico conservado.\n"
        + "FLUJO TRICUSPIDEO\nSin alteraciones.\n",
    ))

    documento = ParseadorEcoDoppler().parsear(texto)

    pulmonar = next(
        seccion
        for seccion in documento.contenido.secciones_texto
        if seccion.nombre.endswith("FLUJO PULMONAR")
    )
    assert pulmonar.texto == "Flujo sistolico conservado."
    ReconciliadorEcoDoppler().reconciliar(documento, texto)


def test_eco_nunca_agrega_referencia_de_hora() -> None:
    """Requirement: "Ausencia explícita cuando el documento no trae hora" (spec
    `momento-del-estudio`) -- el eco no declara ningún `id_campo` de hora: sin
    referencia y sin hallazgo, el 1:1 de cobertura se sostiene solo (design.md,
    decisión 4)."""
    texto = TextoExtraido(paginas=(_DOCUMENTO_COMPLETO,))
    resultado = ParseadorEcoDoppler().parsear(texto)

    assert all("hora" not in fuente.id_campo for fuente in resultado.fuentes)


def test_eco_emite_ausencia_explicita_nunca_un_default_de_medianoche() -> None:
    """Requirement: "Ecocardiograma sin hora emite ausencia, nunca un default"
    -- aserción negativa explícita: `hora_estudio` NUNCA debe ser `time(0, 0)`
    ni ningún otro valor, siempre `None` con `precision_hora = AUSENTE`.

    Nota (documentado en `apply-progress.md`, Fase 7): este test pasa sin
    ningún cambio de código en `eco_doppler.py` -- los defaults de
    `DocumentoParseado` (Fase 1) ya entregan `hora_estudio=None` y
    `precision_hora=AUSENTE` porque `ParseadorEcoDoppler.parsear` nunca los
    sobrescribe. Se agrega igual como red de seguridad explícita: si algún
    cambio futuro empezara a completar la hora del eco con un default, este
    test lo detectaría de inmediato.
    """
    texto = TextoExtraido(paginas=(_DOCUMENTO_COMPLETO,))
    resultado = ParseadorEcoDoppler().parsear(texto)

    assert resultado.hora_estudio is None
    assert resultado.hora_estudio != time(0, 0)
    assert resultado.precision_hora is PrecisionHora.AUSENTE


def test_header_ausente_lanza_error_parseo() -> None:
    texto = TextoExtraido(paginas=("MEDIDAS\nAO | 28 | mm\n",))
    with pytest.raises(ErrorParseo) as info:
        ParseadorEcoDoppler().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO
    assert info.value.detalle_parseo is DetalleParseoIncompleto.NOMBRE_AUSENTE


def test_fecha_ausente_con_nombre_presente_distingue_el_detalle() -> None:
    """`nombre` y `fecha` ausentes compartían el mismo `PARSEO_INCOMPLETO`
    indistinguible -- ahora cada uno es identificable (Tarea "que la
    cuarentena diga qué se rompió")."""
    texto = TextoExtraido(paginas=("Paciente: Fernandez Marta\nMEDIDAS\nAO | 28 | mm\n",))
    with pytest.raises(ErrorParseo) as info:
        ParseadorEcoDoppler().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO
    assert info.value.detalle_parseo is DetalleParseoIncompleto.FECHA_AUSENTE


def test_fecha_ilegible_va_a_cuarentena_con_detalle_distinto_de_ausente() -> None:
    texto = TextoExtraido(
        paginas=("Paciente: Fernandez Marta\nFecha Estudio: 99/99/9999\nMEDIDAS\nAO | 28 | mm\n",)
    )
    with pytest.raises(ErrorParseo) as info:
        ParseadorEcoDoppler().parsear(texto)
    assert info.value.codigo is CodigoErrorDocumento.PARSEO_INCOMPLETO
    assert info.value.detalle_parseo is DetalleParseoIncompleto.FECHA_ILEGIBLE


def test_usa_paginas_ordenadas_y_trunca_campos_que_comparten_linea_visual() -> None:
    """Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
    "Fix: extracción con sort=True + firmas ECG reales"): mismo fix que
    `laboratorio_general.py` -- lee `paginas_ordenadas` y trunca en el
    separador de 2+ espacios para no arrastrar el campo vecino de la misma
    fila visual.
    """
    pagina_sin_ordenar = (
        "Paciente:\nFecha Estudio:\nMEDIDAS\nAO | 28 | mm\nFernandez Marta\n20/03/2024\n"
    )
    pagina_ordenada = (
        "Paciente: Fernandez Marta      Fecha Estudio: 20/03/2024\n"
        "MEDIDAS\nAO | 28 | mm\n"
    )
    texto = TextoExtraido(paginas=(pagina_sin_ordenar,), paginas_ordenadas=(pagina_ordenada,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    assert resultado.identidad.nombre.get_secret_value() == "Fernandez Marta"
    assert resultado.fecha_estudio.isoformat() == "2024-03-20"


def test_header_real_con_paciente_mayusculas_y_fecha_estudio() -> None:
    """Fix post-PR9 #4: el documento real trae `PACIENTE:` (todo en
    mayúsculas) y `Fecha Estudio:` (nunca `Fecha:` a secas), además de
    `N° ESTUDIO:` en mayúsculas y `S.C.` sin dos puntos.
    """
    header_real = (
        "Fecha Estudio: 20/03/2024 PACIENTE: Fernandez Marta      Documento: 28999111\n"
        "Edad: 50 años      N° ESTUDIO: 12345      Peso: 70 kg   Altura: 170 cm   S.C.  1.80 m2\n"
        "Médico Solicitante: Dr. Ruiz\n"
        "\nMEDIDAS\nAO | 28 | mm\n"
    )
    texto = TextoExtraido(paginas=(header_real,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    assert resultado.identidad.nombre.get_secret_value() == "Fernandez Marta"
    assert resultado.fecha_estudio.isoformat() == "2024-03-20"
    assert resultado.identidad.ids_internos[0].get_secret_value() == "12345"
    assert resultado.adicionales["superficie_corporal"] == "1.80 m2"
    assert resultado.adicionales["edad"] == "50 años"


_HEADER_MINIMO = (
    "Paciente: Prueba Sintetica\n"
    "Documento: 11222333\n"
    "Fecha Estudio: 05/06/2025\n"
)


def test_parsea_cuerpo_de_medidas_formato_dos_columnas_sin_pipes() -> None:
    """Fix post-PR9 #4: el documento real trae las medidas en una tabla de
    dos sub-columnas separadas por 2+ espacios (no `|`), cada una con
    nombre + valor + rango de referencia opcional (rango descartado, no hay
    campo en `MedidaEco` para guardarlo). Una fila puede traer solo
    nombre + valor sin rango (p. ej. "VD    NORMAL").

    Calibrado contra una sola muestra real -- el separador de columna
    (`\\s{2,}`) y la heurística nombre/valor/rango podrían no generalizar
    a layouts con más o menos columnas.
    """
    pagina = (
        _HEADER_MINIMO
        + "\n"
        + "MEDIDAS\n"
        + "         MEDIDAS    VALOR       VALOR NORMAL            MEDIDAS    VALOR     VALOR NORMAL\n"
        + "           XX           10 mm        < 20 mm                YY        5 mm      < 9 mm\n"
        + "             ZZ         50 %       > 25%                 WW         NORMAL\n"
    )
    texto = TextoExtraido(paginas=(pagina,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    medidas = {m.nombre: m for m in resultado.contenido.medidas}
    assert set(medidas) == {"XX", "YY", "ZZ", "WW"}
    assert medidas["XX"].valor == "10"
    assert medidas["XX"].unidad == "mm"
    assert medidas["YY"].valor == "5"
    assert medidas["YY"].unidad == "mm"
    assert medidas["ZZ"].valor == "50"
    assert medidas["ZZ"].unidad == "%"
    assert medidas["WW"].valor == "NORMAL"
    assert medidas["WW"].unidad is None


def test_trigger_de_medidas_reconoce_encabezado_real_de_dos_veces_medidas() -> None:
    """Fix post-PR9 #6 (trigger de MEDIDAS, ver
    `sdd/pdf-pii-anonymization/apply-progress`): el documento real NUNCA
    trae una línea exactamente igual a "MEDIDAS" a secas -- la única línea
    que marca el inicio de la tabla es el encabezado repetido
    "MEDIDAS VALOR VALOR NORMAL MEDIDAS VALOR VALOR NORMAL". Sin reconocer
    esa línea como trigger, el modo tabla nunca se activa y las medidas
    quedan en 0 filas.
    """
    pagina = (
        _HEADER_MINIMO
        + "\n"
        + "MEDIDAS    VALOR       VALOR NORMAL            MEDIDAS    VALOR     VALOR NORMAL\n"
        + "           XX           10 mm        < 20 mm                YY        5 mm      < 9 mm\n"
    )
    texto = TextoExtraido(paginas=(pagina,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    medidas = {m.nombre: m for m in resultado.contenido.medidas}
    assert set(medidas) == {"XX", "YY"}
    assert medidas["XX"].valor == "10"
    assert medidas["XX"].unidad == "mm"
    assert medidas["YY"].valor == "5"
    assert medidas["YY"].unidad == "mm"


def test_secciones_anidadas_con_subsecciones_y_dos_puntos() -> None:
    """Fix post-PR9 #4: `MOTILIDAD SEGMENTARIA:` (con dos puntos) matchea
    igual que la variante sin dos puntos; `VALVULAS CARDIACAS` y
    `EVALUACION DE FLUJOS POR DOPPLER` traen subsecciones anidadas
    (AORTICA/MITRAL/... y FLUJO AORTICO/...) que se representan como
    `SeccionTextoEco` propias con nombre compuesto `"padre - hija"` -- ver
    docstring de `_parsear_cuerpo` para la decisión de diseño (el modelo
    `SeccionTextoEco` es plano, sin jerarquía nativa).
    """
    pagina = (
        _HEADER_MINIMO
        + "\n"
        + "MOTILIDAD SEGMENTARIA:\n"
        + "Sin alteraciones.\n"
        + "\n"
        + "VALVULAS CARDIACAS\n"
        + "AORTICA\n"
        + "Valva tricuspide.\n"
        + "MITRAL\n"
        + "Valva normal.\n"
        + "\n"
        + "AURICULAS\n"
        + "IZQUIERDA:\n"
        + "Tamano normal.\n"
        + "DERECHA:\n"
        + "Tamano normal.\n"
        + "\n"
        + "EVALUACION DE FLUJOS POR DOPPLER\n"
        + "FLUJO AORTICO\n"
        + "Sin gradiente significativo.\n"
        + "\n"
        + "CONCLUSIONES\n"
        + "Estudio normal.\n"
    )
    texto = TextoExtraido(paginas=(pagina,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    secciones = {s.nombre: s.texto for s in resultado.contenido.secciones_texto}
    assert secciones["MOTILIDAD SEGMENTARIA"] == "Sin alteraciones."
    assert secciones["VALVULAS CARDIACAS - AORTICA"] == "Valva tricuspide."
    assert secciones["VALVULAS CARDIACAS - MITRAL"] == "Valva normal."
    assert secciones["AURICULAS - IZQUIERDA"] == "Tamano normal."
    assert secciones["AURICULAS - DERECHA"] == "Tamano normal."
    assert secciones["EVALUACION DE FLUJOS POR DOPPLER - FLUJO AORTICO"] == (
        "Sin gradiente significativo."
    )
    assert secciones["CONCLUSIONES"] == "Estudio normal."


def test_firma_heuristica_sin_etiqueta_firma_detecta_nombre_y_matricula() -> None:
    """Fix post-PR9 #4: el documento real NO trae la etiqueta "Firma:" -- el
    nombre del médico informante aparece en una línea propia en mayúsculas
    y, en una línea posterior (no necesariamente adyacente), aparece
    "Matrícula <letra> <número>". Heurística: la última línea "nombre-like"
    (todo mayúsculas, 2+ palabras) vista ANTES de la línea de matrícula se
    usa como nombre de la firma.
    """
    pagina = (
        _HEADER_MINIMO
        + "\n"
        + "CONCLUSIONES\n"
        + "Estudio normal.\n"
        + "\n"
        + "MEDICO DE PRUEBA APELLIDO\n"
        + "\n"
        + "Matricula W 6707\n"
        + "\n"
        + "DIAGNOSTICO POR IMAGENES\n"
    )
    texto = TextoExtraido(paginas=(pagina,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    assert resultado.contenido.firma is not None
    assert resultado.contenido.firma.nombre == "MEDICO DE PRUEBA APELLIDO"
    assert resultado.contenido.firma.matricula == "W 6707"
    # La línea de nombre y la línea "Matricula ..." no deben quedar mezcladas
    # con el texto de CONCLUSIONES.
    conclusiones = next(
        s for s in resultado.contenido.secciones_texto if s.nombre == "CONCLUSIONES"
    )
    assert conclusiones.texto == "Estudio normal."


def test_firma_heuristica_sin_candidato_de_nombre_queda_en_none() -> None:
    """Si aparece una línea de matrícula pero nunca hubo una línea
    nombre-like previa (todo mayúsculas, 2+ palabras) que pudiera ser el
    nombre del médico, es preferible dejar `firma=None` a extraer un
    nombre incorrecto (podría pseudonimizar al médico equivocado).
    """
    pagina = (
        _HEADER_MINIMO
        + "\n"
        + "CONCLUSIONES\n"
        + "Estudio normal.\n"
        + "\n"
        + "Matricula W 6707\n"
    )
    texto = TextoExtraido(paginas=(pagina,))

    resultado = ParseadorEcoDoppler().parsear(texto)

    assert resultado.contenido.firma is None
