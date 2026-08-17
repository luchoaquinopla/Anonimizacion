"""Generadores de texto de layout sintético por tipo de documento (tasks.md 11.1).

Todo dato usado (nombre, DNI, fecha de nacimiento, médicos, texto libre) es
inventado para estos tests, nunca proviene de un documento real (ver
AGENTS.md). Reusa `tests/fixtures/pdf_sintetico.py::crear_pdf_con_texto`
(PR2) para materializar el texto como PDF -- no se duplica esa utilidad acá.

El texto generado respeta los patrones exactos que cada parser real busca
(`parseo/laboratorio_general.py`, `parseo/ecg_mortara.py`,
`parseo/eco_doppler.py`) y los marcadores que `deteccion/firmas/*.py` usa
para clasificar el tipo de documento -- así los tests de integración de
Fase 11 ejercitan el pipeline REAL de extracción+detección+parseo, no un
doble de test.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Sequence

from anonimizacion.ingesta.artefacto import ArtefactoCrudo, FormatoArtefacto

from ..pdf_sintetico import crear_pdf_con_texto


def escribir_pdf(directorio: Path, nombre_archivo: str, paginas: list[str]) -> ArtefactoCrudo:
    """Materializa `paginas` como PDF sintético en `directorio` y arma su `ArtefactoCrudo`."""
    ruta = directorio / f"{nombre_archivo}.pdf"
    crear_pdf_con_texto(ruta, paginas)
    sha256 = hashlib.sha256(ruta.read_bytes()).hexdigest()
    return ArtefactoCrudo(uri=str(ruta), sha256=sha256, formato=FormatoArtefacto.PDF)


def texto_laboratorio(
    *,
    nombre: str,
    dni: str,
    fecha_nac: str,
    numero_peticion: str,
    fecha: str,
    medico_derivante: str = "Dr. Prueba Derivante",
    resultados: Sequence[tuple[str, str, str, str, str]] | None = None,
) -> list[str]:
    """Layout de laboratorio general: header + secciones HEMATOLOGIA/HEMOSTASIA/... .

    `resultados`: tuplas `(seccion, prueba, resultado, unidades, valores_referencia)`.
    """
    filas = resultados or (
        ("HEMATOLOGIA", "Hemoglobina", "14.5", "g/dL", "12-16"),
        ("QUIMICA CLINICA", "Glucosa", "90", "mg/dL", "70-110"),
    )
    por_seccion: dict[str, list[str]] = {}
    for seccion, prueba, resultado, unidades, referencia in filas:
        por_seccion.setdefault(seccion, []).append(f"{prueba} | {resultado} | {unidades} | {referencia}")
    cuerpo = "\n\n".join(f"{seccion}\n" + "\n".join(lineas) for seccion, lineas in por_seccion.items())

    pagina = (
        f"Apellido y Nombre: {nombre}\n"
        f"DNI: {dni}\n"
        f"F.Nacimiento: {fecha_nac}\n"
        f"Medico derivante: {medico_derivante}\n"
        f"No Peticion: {numero_peticion}\n"
        f"Fecha: {fecha}\n"
        "Hora Extraccion: 08:00\n"
        "Origen: Guardia\n\n"
        f"{cuerpo}\n"
    )
    return [pagina]


def texto_ecg(
    *,
    nombre: str,
    id_estudio: str,
    fecha: str,
    hora: str = "09:00:00",
    fecha_nac: str,
    edad_anios: int,
    sexo: str = "Male",
    medico_derivante: str = "Dr Prueba Ecg",
    institucion: str = "Clinica Sintetica",
) -> list[str]:
    """Layout REAL de ECG Mortara (posicional, sin etiquetas `Campo: valor`
    salvo unos pocos campos de pie) -- ver docstring de `parseo/ecg_mortara.py`
    para el detalle de la recalibración post-PR9 contra el layout real.

    `fecha`/`fecha_nac` en formato `DD-MON-YYYY` (mes en inglés, 3 letras
    mayúsculas), igual que el equipo real -- NO `DD/MM/YYYY`.
    """
    pagina = (
        "MORTARA ELI 350\n"
        f"{nombre}~,                    ID:{id_estudio}                  "
        f"{fecha}  {hora}        {institucion}   ROUTINE RECORD\n"
        f"{fecha_nac} ({edad_anios} yr)      {sexo}      Unknown\n"
        "Room:\n"
        "Loc:1\n"
        "                    Vent. rate            72    BPM\n"
        "                    PR interval          160    ms\n"
        "                    QRS duration          90    ms\n"
        "                    QT/QTc            400/420    ms\n"
        "                    P-R-T axes         60  30    40\n"
        "\n"
        "           Technician:\n"
        "           Test ind:\n"
        "Med:\n"
        "\n"
        f"Ordered by:  - {medico_derivante}                          Unconfirmed\n"
    )
    return [pagina]


def texto_eco(
    *,
    nombre: str,
    dni: str,
    numero_estudio: str,
    fecha: str,
    medico_solicitante: str = "Dr. Prueba Solicitante",
    firma_nombre: str = "Dr. Prueba Informante",
    firma_matricula: str = "99999",
    texto_conclusiones: str = "Funcion sistolica conservada",
    medidas: Sequence[tuple[str, str, str]] | None = None,
) -> list[str]:
    """Layout de ecocardiograma Doppler: medidas + texto libre por sección + firma."""
    filas_medidas = medidas or (("AO", "28", "mm"), ("FA", "35", "%"))
    lineas_medidas = "\n".join(f"{nombre_m} | {valor} | {unidad}" for nombre_m, valor, unidad in filas_medidas)

    pagina = (
        "ECOCARDIOGRAMA DOPPLER\n"
        f"Paciente: {nombre}\n"
        f"Documento: {dni}\n"
        f"No Estudio: {numero_estudio}\n"
        f"Fecha: {fecha}\n"
        f"Medico Solicitante: {medico_solicitante}\n"
        "Peso: 70\n"
        "Altura: 170\n"
        "S.C.: 1.8\n\n"
        "MEDIDAS\n"
        f"{lineas_medidas}\n\n"
        "CONCLUSIONES\n"
        f"{texto_conclusiones}\n\n"
        f"Firma: {firma_nombre} - MP{firma_matricula}\n"
    )
    return [pagina]


def texto_layout_no_reconocido() -> list[str]:
    """Un documento sin ningún marcador conocido -- `detectar_tipo` devuelve TIPO_NO_RECONOCIDO."""
    return ["Documento con formato desconocido, sin marcadores de ningun layout soportado."]
