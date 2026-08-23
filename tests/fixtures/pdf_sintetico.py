"""Generador de PDFs sintéticos para tests de extracción/detección.

Todo el texto usado (nombres, DNI, valores) es inventado para estos tests,
nunca proviene de los PDFs de muestra reales. Se genera con `pymupdf`
(la misma librería que usa `extraccion.texto_pymupdf`) para no sumar una
dependencia de test adicional (p. ej. reportlab).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class DocumentoSintetico:
    tipo: str
    ruta: Path


@dataclass(frozen=True)
class CorpusClinicoSintetico:
    documentos: tuple[DocumentoSintetico, ...]
    oraculo: dict[str, dict[str, str]]


def crear_pdf_con_texto(ruta: Path, paginas: list[str]) -> Path:
    """Crea un PDF con una página por cada string de `paginas` (texto nativo)."""
    documento = pymupdf.open()
    for texto in paginas:
        pagina = documento.new_page()
        if texto:
            pagina.insert_text((72, 72), texto, fontsize=11)
    documento.save(ruta)
    documento.close()
    return ruta


def crear_pdf_corrupto(ruta: Path) -> Path:
    """Escribe bytes que no son un PDF válido, simulando un archivo corrupto."""
    ruta.write_bytes(b"esto no es un pdf valido, solo bytes sinteticos de prueba")
    return ruta


def crear_pdf_layout_columnas(
    ruta: Path,
    filas: list[tuple[str, str]],
    *,
    y_inicio: float = 100,
    alto_fila: float = 20,
) -> Path:
    """Crea un PDF de una página con `filas` de (etiqueta, valor) en dos columnas.

    Replica el artefacto de generación real observado contra los PDFs de
    muestra (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
    extracción con sort=True"): el content stream dibuja PRIMERO todas las
    etiquetas de la columna izquierda y DESPUÉS todos los valores de la
    columna derecha, aunque geométricamente cada etiqueta y su valor
    comparten la misma fila (misma altura `y`). El orden de dibujado (el que
    devuelve `page.get_text()` sin `sort=True`) NO es el orden de lectura
    visual: etiqueta y valor quedan muy separados entre sí. Con
    `page.get_text(sort=True)` (orden geométrico) quedan adyacentes en la
    misma línea, como espera un lector humano.
    """
    documento = pymupdf.open()
    pagina = documento.new_page()
    x_etiqueta, x_valor = 72, 250
    for indice, (etiqueta, _valor) in enumerate(filas):
        pagina.insert_text((x_etiqueta, y_inicio + indice * alto_fila), etiqueta, fontsize=11)
    for indice, (_etiqueta, valor) in enumerate(filas):
        pagina.insert_text((x_valor, y_inicio + indice * alto_fila), valor, fontsize=11)
    documento.save(ruta)
    documento.close()
    return ruta


_TAMANO_ECG = (792, 612)
_TAMANO_LABORATORIO = (595, 842)
_TAMANO_ECO = (616, 862)
_NOMBRE_SINTETICO = "Paciente Sintetico"
_FECHA_SINTETICA = date(2024, 1, 15).isoformat()
_MESES_ECG = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _fecha_ecg(fecha: date) -> str:
    return f"{fecha.day:02d}-{_MESES_ECG[fecha.month - 1]}-{fecha.year}"


def _insertar_texto(pagina: pymupdf.Page, punto: tuple[float, float], texto: str, tamano: float = 8) -> None:
    pagina.insert_text(punto, texto, fontsize=tamano, fontname="helv", color=(0, 0, 0))


def _pie_pagina(pagina: pymupdf.Page, numero: int, total: int) -> None:
    ancho = pagina.rect.width
    alto = pagina.rect.height
    pagina.draw_line((36, alto - 38), (ancho - 36, alto - 38), color=(0.45, 0.45, 0.45), width=0.5)
    _insertar_texto(pagina, (ancho - 105, alto - 22), f"Pagina {numero} de {total}", 7)
    _insertar_texto(pagina, (36, alto - 22), "DOCUMENTO SINTETICO - SOLO PRUEBAS", 7)


def _tabla(
    pagina: pymupdf.Page,
    rectangulo: pymupdf.Rect,
    encabezados: tuple[str, ...],
    filas: tuple[tuple[str, ...], ...],
    *,
    tamano: float = 7,
) -> None:
    columnas = len(encabezados)
    alto_fila = rectangulo.height / (len(filas) + 1)
    ancho_columna = rectangulo.width / columnas
    pagina.draw_rect(rectangulo, color=(0.2, 0.2, 0.2), width=0.7)
    for fila in range(1, len(filas) + 1):
        y = rectangulo.y0 + fila * alto_fila
        pagina.draw_line((rectangulo.x0, y), (rectangulo.x1, y), color=(0.45, 0.45, 0.45), width=0.4)
    for columna in range(1, columnas):
        x = rectangulo.x0 + columna * ancho_columna
        pagina.draw_line((x, rectangulo.y0), (x, rectangulo.y1), color=(0.45, 0.45, 0.45), width=0.4)
    for columna, encabezado in enumerate(encabezados):
        _insertar_texto(pagina, (rectangulo.x0 + columna * ancho_columna + 4, rectangulo.y0 + 12), encabezado, tamano)
    for indice_fila, fila in enumerate(filas, start=1):
        for columna, valor in enumerate(fila):
            _insertar_texto(
                pagina,
                (rectangulo.x0 + columna * ancho_columna + 4, rectangulo.y0 + indice_fila * alto_fila + 12),
                valor,
                tamano,
            )


def _crear_ecg(documento: pymupdf.Document, dni: str, fecha: date) -> None:
    pagina = documento.new_page(width=_TAMANO_ECG[0], height=_TAMANO_ECG[1])
    _insertar_texto(pagina, (34, 26), "MORTARA ELI 380 - 12SL ECG REPORT", 11)
    _insertar_texto(
        pagina,
        (34, 46),
        f"{_NOMBRE_SINTETICO}~,      ID:ECG-SINT-{dni[-4:]}      {_fecha_ecg(fecha)}  08:30:00      INSTITUTO FICTICIO   ROUTINE RECORD",
        7,
    )
    _insertar_texto(pagina, (34, 62), "02-FEB-1980 (43 yr)      Female      Unknown", 7)
    _insertar_texto(pagina, (34, 76), "*** PID / NAME MISMATCH ***", 7)
    _insertar_texto(pagina, (34, 90), "Room:      Loc:3", 7)
    medidas = (
        "BPM", "70", "Vent. rate", "ms", "160", "PR interval", "ms", "92",
        "QRS duration", "ms", "QT/QTc", "390/420", "45", "60", "30", "P-R-T axes",
    )
    for indice, linea in enumerate(medidas):
        _insertar_texto(pagina, (34, 112 + indice * 10), linea, 6)
    grilla = pymupdf.Rect(130, 112, 758, 510)
    pagina.draw_rect(grilla, color=(0.75, 0.35, 0.35), width=0.6)
    for x in range(44, 759, 10):
        pagina.draw_line((x, grilla.y0), (x, grilla.y1), color=(0.96, 0.82, 0.82), width=0.25)
    for y in range(156, 511, 10):
        pagina.draw_line((grilla.x0, y), (grilla.x1, y), color=(0.96, 0.82, 0.82), width=0.25)
    for derivacion in range(6):
        base = 172 + derivacion * 54
        _insertar_texto(pagina, (136, base), f"Derivacion {derivacion + 1}", 7)
        puntos: list[tuple[float, float]] = []
        for x in range(196, 750, 8):
            onda = ((x // 8 + derivacion) % 18) - 9
            y = base - (onda if abs(onda) < 4 else onda * 0.35)
            puntos.append((x, y))
        for inicio, fin in pairwise(puntos):
            pagina.draw_line(inicio, fin, color=(0.1, 0.1, 0.1), width=0.55)
    _insertar_texto(pagina, (282, 530), "TRAZADO SINTETICO - NO CLINICO", 8)
    _insertar_texto(pagina, (34, 548), "25 mm/s    10 mm/mV    40 Hz", 8)
    _insertar_texto(pagina, (430, 548), "Technician: Operador Sintetico", 7)
    _insertar_texto(pagina, (430, 560), "Test ind: Routine", 7)
    _insertar_texto(pagina, (34, 574), "Ordered by: - Dr Profesional Sintetico      Unconfirmed", 7)
    _pie_pagina(pagina, 1, 1)


def _encabezado_laboratorio(pagina: pymupdf.Page, dni: str, fecha: date) -> None:
    _insertar_texto(pagina, (42, 38), "LABORATORIO DE ANALISIS CLINICOS", 13)
    _insertar_texto(pagina, (42, 58), "Apellido y Nombre: " + _NOMBRE_SINTETICO, 8)
    _insertar_texto(pagina, (42, 72), "DNI: " + dni + "    F.Nacimiento : 02/02/1980    Edad: 44", 8)
    _insertar_texto(pagina, (42, 86), "Medico: Profesional Sintetico    No Peticion: PET-SINT-001", 8)
    _insertar_texto(pagina, (42, 100), f"Fecha: {fecha:%d/%m/%Y}    Hora de Extraccion: 08:30    Origen: Ambulatorio", 8)
    pagina.draw_line((42, 110), (553, 110), color=(0.2, 0.2, 0.2), width=0.6)


def _tabla_laboratorio(
    pagina: pymupdf.Page,
    filas: tuple[tuple[str, str, str, str], ...],
    *,
    y_inicio: float,
    y_fin: float,
) -> None:
    posiciones_x = (42, 330, 390, 460, 553)
    alto_fila = (y_fin - y_inicio) / (len(filas) + 1)
    pagina.draw_rect(pymupdf.Rect(42, y_inicio, 553, y_fin), color=(0.2, 0.2, 0.2), width=0.7)
    for x in posiciones_x[1:-1]:
        pagina.draw_line((x, y_inicio), (x, y_fin), color=(0.45, 0.45, 0.45), width=0.4)
    for indice in range(1, len(filas) + 1):
        y = y_inicio + indice * alto_fila
        pagina.draw_line((42, y), (553, y), color=(0.45, 0.45, 0.45), width=0.4)
    encabezados = ("Pruebas", "Resultado", "Unidades", "Valores de Referencia")
    for columna, encabezado in enumerate(encabezados):
        _insertar_texto(pagina, (posiciones_x[columna] + 4, y_inicio + 11), encabezado, 6)
    for indice, fila in enumerate(filas, start=1):
        for columna, valor in enumerate(fila):
            if valor:
                _insertar_texto(
                    pagina,
                    (posiciones_x[columna] + 4, y_inicio + indice * alto_fila + 11),
                    valor,
                    6,
                )


def _crear_laboratorio(documento: pymupdf.Document, dni: str, fecha: date) -> None:
    paginas: tuple[tuple[tuple[str, str, str, str], ...], ...] = (
        (
            ("HEMATOLOGIA", "", "", ""),
            ("Eritrosedimentacion", "10", "mm/h", "1 - 20"),
            ("HEMOGRAMA", "", "", ""),
            ("Hematocrito", "42", "%", "36 - 46"),
            ("Globulos Rojos", "4500", "mil/uL", "4000 - 5500"),
            ("Hemoglobina", "14.2", "g/dL", "12 - 16"),
            ("Volumen Corpuscular Medio", "90", "fL", "80 - 100"),
            ("Hemoglobina Corpuscular Media", "30", "pg", "27 - 33"),
            ("Conc. de Hba Corpuscular Media", "33", "g/dL", "32 - 36"),
            ("RDW-SD", "44", "fL", "37 - 54"),
            ("RDW-CV", "13", "%", "11 - 15"),
            ("Plaquetas", "250", "mil/uL", "150 - 450"),
            ("Volumen Plaquetario Medio", "10", "fL", "7 - 12"),
            ("Globulos Blancos", "7000", "/uL", "4000 - 11000"),
            ("FORMULA LEUCOCITARIA", "", "", ""),
            ("Neutrofilos", "55", "%", "40 - 70"),
            ("Eosinofilos", "2", "%", "0 - 5"),
            ("Basofilos", "1", "%", "0 - 2"),
            ("Linfocitos", "35", "%", "20 - 45"),
        ),
        (
            ("Monocitos", "7", "%", "2 - 10"),
            ("Cayados", "1", "%", "0 - 5"),
            ("Granulocitos inmaduros", "1", "%", "0 - 3"),
            ("Neutrofilos", "55", "%", "40 - 70"),
            ("Eosinofilos", "2", "%", "0 - 5"),
            ("Basofilos", "1", "%", "0 - 2"),
            ("Linfocitos", "35", "%", "20 - 45"),
            ("Monocitos", "7", "%", "2 - 10"),
            ("Cayados", "1", "%", "0 - 5"),
            ("Granulocitos inmaduros", "1", "%", "0 - 3"),
            ("HEMOSTASIA", "", "", ""),
            ("Tiempo de Protrombina", "12", "s", "10 - 14"),
            ("RIN", "1", "", "0 - 2"),
            ("Tiempo de Tromboplastina APTT", "30", "s", "25 - 40"),
            ("R", "1", "", ""),
            ("QUIMICA CLINICA", "", "", ""),
            ("Glucemia", "90", "mg/dL", "70 - 110"),
            ("Uremia", "30", "mg/dL", "15 - 45"),
            ("Creatinina serica", "0.9", "mg/dL", ""),
            ("Filtrado Glomerular Estimado (CKD-EPI 2021)", "102", "mL/min", ""),
        ),
        (
            ("IONOGRAMA SERICO", "", "", ""),
            ("Sodio", "140", "mEq/L", "135 - 145"),
            ("Potasio", "4.1", "mEq/L", "3.5 - 5.1"),
        ),
    )
    limites = ((130, 720), (130, 520), (130, 310))
    for numero, filas in enumerate(paginas, start=1):
        pagina = documento.new_page(width=_TAMANO_LABORATORIO[0], height=_TAMANO_LABORATORIO[1])
        _encabezado_laboratorio(pagina, dni, fecha)
        _tabla_laboratorio(pagina, filas, y_inicio=limites[numero - 1][0], y_fin=limites[numero - 1][1])
        _insertar_texto(pagina, (42, limites[numero - 1][1] + 25), "Resultados sinteticos para validacion de parser", 8)
        _pie_pagina(pagina, numero, len(paginas))


def _encabezado_eco(pagina: pymupdf.Page, dni: str, fecha: date) -> None:
    _insertar_texto(pagina, (180, 35), "SERVICIO DE ECOCARDIOGRAFIA", 13)
    _insertar_texto(pagina, (170, 55), "ECOGRAFIA DOPPLER COLOR CARDIACA", 11)
    _insertar_texto(
        pagina,
        (42, 76),
        f"PACIENTE: {_NOMBRE_SINTETICO}      Documento: {dni}      Fecha Estudio: {fecha:%d/%m/%Y}",
        8,
    )
    _insertar_texto(
        pagina,
        (42, 92),
        "Edad: 44 anos      Nº ESTUDIO: ECO-SINT-001      Peso: 70 kg      Altura: 165 cm      S.C. 1.75 m2",
        8,
    )
    _insertar_texto(pagina, (42, 106), "Medico Solicitante: Profesional Sintetico", 8)
    pagina.draw_line((42, 112), (574, 112), color=(0.2, 0.2, 0.2), width=0.6)


def _crear_ecocardiograma(documento: pymupdf.Document, dni: str, fecha: date) -> None:
    primera = documento.new_page(width=_TAMANO_ECO[0], height=_TAMANO_ECO[1])
    _encabezado_eco(primera, dni, fecha)
    _insertar_texto(primera, (250, 128), "VALORES HALLADOS", 9)
    _tabla(
        primera,
        pymupdf.Rect(42, 140, 574, 270),
        ("MEDIDAS", "VALOR", "VALOR NORMAL", "MEDIDAS", "VALOR", "VALOR NORMAL"),
        (
            ("AO", "31 mm", "< 41 mm", "SEPTUM", "9 mm", "< 11 mm"),
            ("AI", "35 mm", "< 40 mm", "P.POSTERIOR", "9 mm", "< 11 mm"),
            ("DDVI", "50 mm", "< 52 mm", "VD", "NORMAL", ""),
            ("DSVI", "32 mm", "VARIABLE", "PULMON", "NORMAL", ""),
            ("FA", "36 %", "> 30 %", "AD", "NORMAL", ""),
        ),
        tamano=6,
    )
    bloques = (
        (300, "MOTILIDAD SEGMENTARIA", "Descripcion sintetica de motilidad."),
        (345, "AURICULAS", "Descripcion sintetica de ambas auriculas."),
        (390, "VALVULAS CARDIACAS", ""),
        (415, "AORTICA", "Descripcion sintetica de valvula aortica."),
        (455, "MITRAL", "Descripcion sintetica de valvula mitral."),
        (495, "PULMONAR", "Descripcion sintetica de valvula pulmonar."),
        (535, "TRICUSPIDEA", "Descripcion sintetica de valvula tricuspidea."),
        (575, "PERICARDIO", "Descripcion sintetica del pericardio."),
        (615, "EVALUACION DE FLUJOS POR DOPPLER", ""),
        (640, "FLUJO AORTICO", "Descripcion sintetica del flujo aortico."),
        (680, "FLUJO MITRAL", "Descripcion sintetica del flujo mitral."),
        (720, "FLUJO PULMONAR", ""),
    )
    for y, titulo, contenido in bloques:
        _insertar_texto(primera, (42, y), titulo, 8)
        if contenido:
            _insertar_texto(primera, (62, y + 15), contenido, 7)
    _pie_pagina(primera, 1, 2)

    segunda = documento.new_page(width=_TAMANO_ECO[0], height=_TAMANO_ECO[1])
    _encabezado_eco(segunda, dni, fecha)
    _insertar_texto(segunda, (62, 135), "Descripcion sintetica del flujo pulmonar.", 7)
    _insertar_texto(segunda, (42, 165), "FLUJO TRICUSPIDEO", 8)
    _insertar_texto(segunda, (62, 180), "Descripcion sintetica del flujo tricuspideo.", 7)
    _insertar_texto(segunda, (250, 220), "CONCLUSIONES", 9)
    _insertar_texto(segunda, (62, 245), "Conclusiones sinteticas sin validez clinica.", 8)
    _insertar_texto(segunda, (360, 330), "PROFESIONAL MEDICO SINTETICO", 8)
    _insertar_texto(segunda, (390, 348), "Matricula W 9001", 8)
    _insertar_texto(segunda, (365, 370), "DIAGNOSTICO POR IMAGENES", 8)
    _pie_pagina(segunda, 2, 2)


def generar_corpus_clinico(
    directorio: Path,
    *,
    semilla: int,
    fechas_estudio: dict[str, date] | None = None,
    registrar_pii: Callable[[tuple[str, ...]], None] | None = None,
) -> CorpusClinicoSintetico:
    """Genera un episodio sintético local con su oráculo libre de PII."""
    directorio.mkdir(parents=True, exist_ok=True)
    rng = random.Random(semilla)
    dni = str(rng.randint(10_000_000, 49_999_999))
    if registrar_pii is not None:
        registrar_pii((
            _NOMBRE_SINTETICO, dni, "02/02/1980", "02-FEB-1980", f"ECG-SINT-{dni[-4:]}",
            "PET-SINT-001", "ECO-SINT-001", "Profesional Sintetico",
            "Profesional Medico Sintetico", "Operador Sintetico", "W 9001",
        ))
    fecha_base = date.fromisoformat(_FECHA_SINTETICA)
    fechas = {tipo: fecha_base for tipo in ("ecg", "laboratorio", "ecocardiograma")}
    fechas.update(fechas_estudio or {})
    generadores = {
        "ecg": _crear_ecg,
        "laboratorio": _crear_laboratorio,
        "ecocardiograma": _crear_ecocardiograma,
    }
    documentos: list[DocumentoSintetico] = []
    for tipo, generador in generadores.items():
        ruta = directorio / f"{tipo}.pdf"
        documento = pymupdf.open()
        generador(documento, dni, fechas[tipo])
        documento.save(ruta)
        documento.close()
        documentos.append(DocumentoSintetico(tipo, ruta))
    oraculo = {
        tipo: {"tipo": tipo, "fecha_estudio": fechas[tipo].isoformat(), "resultado_esperado": "aprobado"}
        for tipo in generadores
    }
    return CorpusClinicoSintetico(tuple(documentos), oraculo)
