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
    medico_derivante: str = "Dr. Prueba Ecg",
    institucion: str = "Clinica Sintetica",
) -> list[str]:
    """Layout de ECG Mortara: `identidad.dni`/`fecha_nac` SIEMPRE quedan en `None`

    (ver `parseo/ecg_mortara.py`, hardcodeado -- el header real de ECG nunca
    trae fecha de nacimiento, ver spec `document-parsing`). Ver el reporte
    final de PR9 para el gap que esto deja abierto en `pseudonymous-linkage`.
    """
    pagina = (
        "MORTARA ELI 350\n"
        f"Nombre: {nombre}\n"
        f"ID Estudio: {id_estudio}\n"
        f"Fecha: {fecha} 09:00\n"
        f"Institucion: {institucion}\n"
        f"Medico derivante: {medico_derivante}\n"
        "Vent Rate: 72\n"
        "PR: 160\n"
        "QRS: 90\n"
        "QT/QTc: 400/420\n"
        "Ejes P-R-T: P60 R30 T40\n"
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
