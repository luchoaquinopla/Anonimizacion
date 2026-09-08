"""Generador de PDFs sintéticos para tests de extracción/detección.

Todo el texto usado (nombres, DNI, valores) es inventado para estos tests,
nunca proviene de los PDFs de muestra reales. Se genera con `pymupdf`
(la misma librería que usa `extraccion.texto_pymupdf`) para no sumar una
dependencia de test adicional (p. ej. reportlab).

Tarea "invertir la dirección del corpus sintético" (ver
`tests/fixtures/matriz_cobertura_sinteticos.md` y
`tests/fixtures/plantilla_documento.py`): `generar_corpus_clinico` ya NO
reconstruye el layout a mano campo por campo -- eso es exactamente lo que
dejaba huecos de cobertura sin que ningún test se enterara (nueve veces en
este proyecto). Ahora dibuja el contenido de `plantilla_documento.py`, que a
su vez deriva del fixture parseable real versionado
(`tests/fixtures/parseables/{tipo}-01.txt`) con la identidad sustituida por
documento. Lo poco que sigue hardcodeado acá (pie de página, banner de tipo
de documento, un puñado de etiquetas de calibración como "PID / NAME
MISMATCH" o "25 mm/s") es contenido NO clínico que ningún parser real exige
de la plantilla -- son marcadores de una funcionalidad de parser puntual
(`advertencia_equipo`, unidades de calibración del trazado) o simple
decoración, nunca datos de un paciente.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pymupdf

from .plantilla_documento import (
    FragmentoPagina,
    generar_identidad_sintetica,
    preparar_ecg,
    preparar_ecocardiograma,
    preparar_laboratorio,
)


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


def crear_pdf_bytes_con_texto(paginas: list[str]) -> bytes:
    """Como `crear_pdf_con_texto`, pero devuelve los bytes en memoria (sin tocar disco).

    Usado por los tests de `extraer_texto_de_flujo` (fase 6, openspec
    `puerto-de-ingesta`): el flujo del pipeline ya no pasa por una ruta de
    filesystem, así que el PDF sintético tampoco debería necesitar una.
    """
    documento = pymupdf.open()
    for texto in paginas:
        pagina = documento.new_page()
        if texto:
            pagina.insert_text((72, 72), texto, fontsize=11)
    datos = documento.tobytes()
    documento.close()
    return datos


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
_FECHA_SINTETICA = date(2024, 1, 15).isoformat()


def _insertar_texto(pagina: pymupdf.Page, punto: tuple[float, float], texto: str, tamano: float = 8) -> None:
    pagina.insert_text(punto, texto, fontsize=tamano, fontname="helv", color=(0, 0, 0))


def _pie_pagina(pagina: pymupdf.Page, numero: int, total: int) -> None:
    ancho = pagina.rect.width
    alto = pagina.rect.height
    pagina.draw_line((36, alto - 38), (ancho - 36, alto - 38), color=(0.45, 0.45, 0.45), width=0.5)
    _insertar_texto(pagina, (ancho - 105, alto - 22), f"Pagina {numero} de {total}", 7)
    _insertar_texto(pagina, (36, alto - 22), "DOCUMENTO SINTETICO - SOLO PRUEBAS", 7)


def _dibujar_cuerpo_plantilla(
    pagina: pymupdf.Page,
    texto_pagina: str,
    *,
    fontsize: float = 5.0,
    interlinea: float = 7.2,
    margen_x: float = 18,
    margen_y: float = 22,
    max_indentacion: int = 70,
) -> None:
    """Dibuja `texto_pagina` (una línea de la plantilla real por renglón) como
    UN `insert_text` por línea, de arriba hacia abajo.

    Cada línea es un único span de texto -- no hace falta reconciliar
    columnas dibujadas por separado -- así que tanto `page.get_text()` (orden
    de dibujado) como `page.get_text(sort=True)` (orden geométrico)
    devuelven, en la práctica, el mismo contenido: exactamente lo que
    laboratorio/eco necesitan (leen `paginas_ordenadas`) y lo que alcanza
    para que la detección de tipo (que lee `paginas`) encuentre sus
    marcadores en cualquier parte del texto. La indentación original de la
    plantilla se aproxima con la cantidad de espacios iniciales -- sólo para
    que el layout no quede pegado al margen izquierdo; no pretende
    reproducir la posición exacta del PDF real, que no hace falta para
    ningún test de extracción de texto de este módulo.
    """
    alto_maximo = pagina.rect.height - margen_y
    y = margen_y
    for linea in texto_pagina.splitlines():
        contenido = linea.strip()
        if contenido:
            indentacion = min(len(linea) - len(linea.lstrip(" ")), max_indentacion)
            x = margen_x + indentacion * 1.8
            _insertar_texto(pagina, (x, y), contenido, fontsize)
        y += interlinea
        if y > alto_maximo:
            break


def _dibujar_fragmentos_plantilla(
    pagina: pymupdf.Page,
    fragmentos: tuple[FragmentoPagina, ...],
    *,
    fontsize: float = 5.0,
    interlinea: float = 7.2,
    margen_x: float = 18,
    margen_y: float = 22,
    espacio_columna_ancho: float = 12.0,
    espacio_columna_angosto: float = 3.0,
) -> None:
    """Como `_dibujar_cuerpo_plantilla`, pero dibuja `fragmentos` -- tokens de
    columna individuales, no una línea entera por `insert_text` -- en el
    ORDEN en que `fragmentos` los declara (orden de dibujado real, ver
    `plantilla_documento._fragmentos_en_orden_de_dibujado`), cada uno
    posicionado según su propia (fila, columna) de la grilla geométrica.

    Hallazgo (reporte de la tarea "usar la plantilla completa"): la primera
    versión ubicaba la X de cada fragmento escalando el OFFSET de caracter
    del token dentro de la fila original (`x = offset * 1.8`) -- una
    aproximación que valía cuando cada fila era UN solo `insert_text`, pero
    con más de un fragmento por fila subestimaba el ancho real renderizado a
    `fontsize` chico: "F.Nacimiento :" (14 caracteres) ocupa más de los
    17*1.8=30.6pt que el offset del siguiente token asumía disponibles, así
    que `get_text(sort=True)` terminaba intercalando el valor DENTRO del
    texto de la etiqueta ("F.Nacimiento15/01/1946:"). Ahora la X se calcula
    por fila, en dos pasadas: se agrupan los fragmentos por `fila`, se
    ordenan por `columna` (orden IZQUIERDA A DERECHA real, no el de emisión)
    y se acumula el ancho real de cada token (`pymupdf.get_text_length`) más
    un espacio fijo -- garantiza que dos columnas vecinas nunca se solapen,
    sin importar el orden en que después se ITERE `fragmentos` para dibujar.

    La posición (X/Y) sale de `fragmento.fila`/`fragmento.columna`, NUNCA del
    orden en que se itera esta lista -- por eso, a diferencia de
    `_dibujar_cuerpo_plantilla`, acá NO se puede cortar apenas se excede
    `alto_maximo`: los fragmentos no llegan ordenados por fila, así que se
    filtran (se saltean, no se corta el loop) los que caerían fuera de
    página."""
    alto_maximo = pagina.rect.height - margen_y
    por_fila: dict[int, list[FragmentoPagina]] = {}
    for fragmento in fragmentos:
        por_fila.setdefault(fragmento.fila, []).append(fragmento)

    x_de_columna: dict[tuple[int, int], float] = {}
    for fila_idx, items in por_fila.items():
        items_ordenados = sorted(items, key=lambda f: f.columna)
        x = margen_x
        for indice, item in enumerate(items_ordenados):
            x_de_columna[(fila_idx, item.columna)] = x
            ancho = pymupdf.get_text_length(item.texto, fontsize=fontsize, fontname="helv")
            siguiente = items_ordenados[indice + 1] if indice + 1 < len(items_ordenados) else None
            # El espacio que sigue a ESTE token depende de si el PRÓXIMO
            # token abre un grupo de columna nuevo (`separador_ancho`) o es
            # su continuación unida por un solo espacio en la plantilla.
            espacio = espacio_columna_angosto
            if siguiente is not None and siguiente.separador_ancho:
                espacio = espacio_columna_ancho
            x += ancho + espacio

    for fragmento in fragmentos:
        y = margen_y + fragmento.fila * interlinea
        if y > alto_maximo:
            continue
        x = x_de_columna[(fragmento.fila, fragmento.columna)]
        _insertar_texto(pagina, (x, y), fragmento.texto, fontsize)


def generar_corpus_clinico(
    directorio: Path,
    *,
    semilla: int,
    fechas_estudio: dict[str, date] | None = None,
    registrar_pii: Callable[[tuple[str, ...]], None] | None = None,
) -> CorpusClinicoSintetico:
    """Genera un episodio sintético local con su oráculo libre de PII.

    El cuerpo de cada documento se dibuja a partir de la plantilla real
    versionada (`tests/fixtures/plantilla_documento.py`), con la identidad
    sustituida por esta llamada -- ver el docstring del módulo.
    """
    directorio.mkdir(parents=True, exist_ok=True)
    rng = random.Random(semilla)
    dni = str(rng.randint(10_000_000, 49_999_999))
    fecha_base = date.fromisoformat(_FECHA_SINTETICA)
    fechas = {tipo: fecha_base for tipo in ("ecg", "laboratorio", "ecocardiograma")}
    fechas.update(fechas_estudio or {})
    identidad = generar_identidad_sintetica(rng, dni, fechas["laboratorio"])

    paginas_lab, pii_lab = preparar_laboratorio(rng, identidad, fechas["laboratorio"])
    paginas_eco, pii_eco = preparar_ecocardiograma(rng, identidad, fechas["ecocardiograma"])
    paginas_ecg, pii_ecg = preparar_ecg(rng, identidad, fechas["ecg"])

    if registrar_pii is not None:
        registrar_pii(pii_lab + pii_eco + pii_ecg)

    documentos: list[DocumentoSintetico] = []
    for tipo, paginas_texto, tamano, banner in (
        ("ecg", paginas_ecg, _TAMANO_ECG, None),
        ("laboratorio", paginas_lab, _TAMANO_LABORATORIO, "LABORATORIO DE ANALISIS CLINICOS (SINTETICO)"),
        ("ecocardiograma", paginas_eco, _TAMANO_ECO, None),
    ):
        ruta = directorio / f"{tipo}.pdf"
        documento = pymupdf.open()
        total = len(paginas_texto)
        for numero, texto_pagina in enumerate(paginas_texto, start=1):
            pagina = documento.new_page(width=tamano[0], height=tamano[1])
            if banner is not None:
                _insertar_texto(pagina, (42, 12), banner, 9)
            margen_y = 24 if banner else 18
            if tipo == "ecg":
                # ECG dibuja línea por línea, en orden de dibujado real (ver
                # `preparar_ecg`) -- no necesita reagrupar por columna: su
                # parser sólo lee `paginas` (orden de dibujado), nunca
                # `paginas_ordenadas` (ver `extraccion/texto_pymupdf.py`).
                _dibujar_cuerpo_plantilla(pagina, texto_pagina, margen_y=margen_y)
            else:
                # Laboratorio/eco dibujan fragmento por fragmento (token de
                # columna), posicionados según la grilla geométrica pero
                # EMITIDOS en orden de dibujado -- ver
                # `plantilla_documento._fragmentos_en_orden_de_dibujado`.
                _dibujar_fragmentos_plantilla(pagina, texto_pagina, margen_y=margen_y)
            if tipo == "ecg":
                # Separadas por al menos 20pt entre sí y del pie de página
                # (`_pie_pagina` dibuja desde `alto - 38`): a menos distancia,
                # `get_text(sort=True)` las agrupa en la misma línea que la
                # vecina y las intercala carácter a carácter -- ver hallazgo
                # en `mem_save` de esta tarea.
                _insertar_texto(pagina, (34, 26), "MORTARA ELI 380 - 12SL ECG REPORT (SINTETICO)", 9)
                _insertar_texto(pagina, (34, 500), "*** PID / NAME MISMATCH ***", 7)
                _insertar_texto(pagina, (34, 522), "TRAZADO SINTETICO - NO CLINICO", 7)
                _insertar_texto(pagina, (250, 522), "25 mm/s    10 mm/mV    40 Hz", 7)
            if tipo == "ecocardiograma" and numero == total:
                # "DIAGNOSTICO POR IMAGENES" (especialidad bajo la firma) no
                # aparece en la plantilla real usada (`eco-01.txt`) -- no es
                # que se haya enmascarado, simplemente esta muestra no trae
                # sello de especialidad. Es una etiqueta NO clínica que
                # `parseo/eco_doppler.py::_TEXTO_FIRMA_EXCLUIDO` y
                # `reconciliacion/eco_doppler.py::_WHITELIST_ECO` YA conocen
                # explícitamente (para no confundirla con el nombre del
                # firmante) -- se agrega acá, igual que "PID / NAME MISMATCH"
                # en el ECG, para seguir calibrando esa rama sin depender de
                # que la muestra real la incluya.
                _insertar_texto(pagina, (365, 340), "DIAGNOSTICO POR IMAGENES", 7)
            _pie_pagina(pagina, numero, total)
        documento.save(ruta)
        documento.close()
        documentos.append(DocumentoSintetico(tipo, ruta))

    oraculo = {
        tipo: {"tipo": tipo, "fecha_estudio": fechas[tipo].isoformat(), "resultado_esperado": "aprobado"}
        for tipo in ("ecg", "laboratorio", "ecocardiograma")
    }
    return CorpusClinicoSintetico(tuple(documentos), oraculo)
