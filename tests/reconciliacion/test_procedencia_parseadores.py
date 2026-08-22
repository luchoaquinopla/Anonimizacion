from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import ParseadorEcgMortara
from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler
from anonimizacion.parseo.laboratorio_general import ParseadorLaboratorioGeneral


def test_parseadores_emiten_referencias_no_sensibles_por_coleccion() -> None:
    ecg = TextoExtraido(("Nombre Sintetico~, ID:11 05-JUN-2025 10:00:00 HOSPITAL\nVent. rate 68 BPM",))
    laboratorio = TextoExtraido(("Apellido y Nombre: Nombre Sintetico\nNº Petición: 9\nFecha: 10/01/2025\nHEMATOLOGIA\nPrueba | 10 | u",))
    eco = TextoExtraido(("Paciente: Nombre Sintetico\nFecha Estudio: 10/01/2025\nMEDIDAS\nAO | 28 | mm\nCONCLUSIONES\nTexto sintetico.",))

    fuentes_ecg = ParseadorEcgMortara().parsear(ecg).fuentes
    fuentes_laboratorio = ParseadorLaboratorioGeneral().parsear(laboratorio).fuentes
    fuentes_eco = ParseadorEcoDoppler().parsear(eco).fuentes

    assert {fuente.id_campo for fuente in fuentes_ecg} >= {"ecg.nombre", "ecg.id_estudio", "ecg.fecha_estudio", "ecg.vent_rate"}
    assert [(fuente.id_campo, fuente.ordinal) for fuente in fuentes_laboratorio] == [("laboratorio.resultado", 0)]
    assert {fuente.id_campo for fuente in fuentes_eco} >= {"eco.nombre", "eco.fecha_estudio", "eco.medida", "eco.seccion"}


def test_eco_ubica_fuentes_en_la_pagina_que_contiene_el_dato() -> None:
    texto = TextoExtraido((
        "Paciente: Nombre Sintetico\nNº Estudio: E-1\nFecha Estudio: 10/01/2025",
        "MEDIDAS\nAO | 28 | mm\nCONCLUSIONES\nTexto sintetico.\nFirma: Medico Sintetico - MP 99",
    ))
    fuentes = ParseadorEcoDoppler().parsear(texto).fuentes
    assert {(fuente.id_campo, fuente.pagina) for fuente in fuentes if fuente.id_campo in {"eco.medida", "eco.seccion", "eco.firma"}} == {("eco.medida", 2), ("eco.seccion", 2), ("eco.firma", 2)}
