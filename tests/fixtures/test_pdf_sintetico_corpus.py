from __future__ import annotations

import hashlib
import random
import socket
from datetime import date

import pymupdf

from tests.fixtures.pdf_sintetico import _FECHA_SINTETICA, generar_corpus_clinico
from tests.fixtures.plantilla_documento import IdentidadSintetica, generar_identidad_sintetica


def _identidad_de_semilla(semilla: int) -> IdentidadSintetica:
    """Reproduce el mismo cómputo de identidad que `generar_corpus_clinico`
    (mismo orden de consumo de `rng`) para poder afirmar sobre el nombre y el
    DNI generados sin duplicar la lógica ni hardcodear un valor fijo -- desde
    la tarea "invertir la dirección del corpus sintético", cada documento
    tiene una identidad sintética DISTINTA por semilla (antes era siempre
    "Paciente Sintetico"), así que un test que afirme sobre el nombre
    necesita poder recalcularlo."""
    rng = random.Random(semilla)
    dni = str(rng.randint(10_000_000, 49_999_999))
    fecha_base = date.fromisoformat(_FECHA_SINTETICA)
    return generar_identidad_sintetica(rng, dni, fecha_base)


def test_corpus_con_misma_semilla_repite_oraculo_y_tres_tipos(tmp_path) -> None:
    primero = generar_corpus_clinico(tmp_path / "uno", semilla=7)
    segundo = generar_corpus_clinico(tmp_path / "dos", semilla=7)

    assert primero.oraculo == segundo.oraculo
    assert {documento.tipo for documento in primero.documentos} == {"ecg", "laboratorio", "ecocardiograma"}
    assert all(documento.ruta.read_bytes().startswith(b"%PDF") for documento in primero.documentos)


def test_corpus_usa_pii_sintetica_y_no_la_expone_en_oraculo(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=9)
    identidad = _identidad_de_semilla(9)

    contenido = "\n".join(pymupdf.open(documento.ruta)[0].get_text() for documento in corpus.documentos)
    assert identidad.nombre_lab in contenido
    assert identidad.dni not in str(corpus.oraculo)
    assert all("dni" not in claves for claves in corpus.oraculo.values())


def test_dos_semillas_distintas_generan_documentos_con_identidad_distinta(tmp_path) -> None:
    """Tarea "invertir la dirección del corpus sintético", requisito 2: los
    documentos deben seguir siendo DISTINTOS entre sí (no sólo el nombre
    "Paciente Sintetico" con un DNI distinto como antes) -- si no, el corpus
    deja de ejercitar la deduplicación por SHA-256 y el banco de carga mide
    una mezcla que no existe. Se compara el hash de CONTENIDO del PDF
    completo (no sólo la identidad), asi que tambien cubre que el resto del
    documento (fechas, numero de peticion/estudio) varía por semilla."""
    primero = generar_corpus_clinico(tmp_path / "uno", semilla=101)
    segundo = generar_corpus_clinico(tmp_path / "dos", semilla=102)

    for tipo in ("ecg", "laboratorio", "ecocardiograma"):
        ruta_1 = next(d.ruta for d in primero.documentos if d.tipo == tipo)
        ruta_2 = next(d.ruta for d in segundo.documentos if d.tipo == tipo)
        assert hashlib.sha256(ruta_1.read_bytes()).digest() != hashlib.sha256(ruta_2.read_bytes()).digest()

    identidad_1 = _identidad_de_semilla(101)
    identidad_2 = _identidad_de_semilla(102)
    assert identidad_1.dni != identidad_2.dni
    assert identidad_1.nombre_lab != identidad_2.nombre_lab


def test_ecg_reproduce_contrato_visual_y_textual_de_layout(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=13)
    ruta = next(documento.ruta for documento in corpus.documentos if documento.tipo == "ecg")

    documento = pymupdf.open(ruta)
    pagina = documento[0]
    texto = pagina.get_text("text", sort=True)

    assert (round(pagina.rect.width), round(pagina.rect.height)) == (792, 612)
    assert "PID / NAME MISMATCH" in texto
    assert "Vent. rate" in texto
    assert "PR interval" in texto
    assert "QRS duration" in texto
    assert "QT/QTc" in texto
    assert "P-R-T axes" in texto
    assert "TRAZADO SINTETICO - NO CLINICO" in texto
    assert "25 mm/s" in texto
    assert "10 mm/mV" in texto
    assert texto.index("Vent. rate") < texto.index("TRAZADO SINTETICO - NO CLINICO") < texto.index("25 mm/s")
    documento.close()


def test_laboratorio_y_eco_preservan_paginacion_y_secciones_extraibles(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=17)
    rutas = {documento.tipo: documento.ruta for documento in corpus.documentos}

    laboratorio = pymupdf.open(rutas["laboratorio"])
    assert len(laboratorio) == 3
    assert all((round(pagina.rect.width), round(pagina.rect.height)) == (595, 842) for pagina in laboratorio)
    texto_laboratorio = [pagina.get_text("text", sort=True) for pagina in laboratorio]
    assert all("LABORATORIO DE ANALISIS CLINICOS" in texto for texto in texto_laboratorio)
    assert "HEMATOLOGIA" in texto_laboratorio[0]
    assert "Apellido y Nombre:" in texto_laboratorio[0]
    assert "QUÍMICA CLÍNICA" in texto_laboratorio[1]
    assert "Pagina 3 de 3" in texto_laboratorio[2]
    assert texto_laboratorio[0].index("Apellido y Nombre:") < texto_laboratorio[0].index("HEMATOLOGIA")
    laboratorio.close()

    ecocardiograma = pymupdf.open(rutas["ecocardiograma"])
    assert len(ecocardiograma) == 2
    assert all((round(pagina.rect.width), round(pagina.rect.height)) == (616, 862) for pagina in ecocardiograma)
    texto_eco = [pagina.get_text("text", sort=True) for pagina in ecocardiograma]
    assert "ECOGRAFIA DOPPLER COLOR CARDIACA" in texto_eco[0]
    assert "MEDIDAS" in texto_eco[0]
    assert "MOTILIDAD SEGMENTARIA" in texto_eco[0]
    assert "VALVULAS CARDIACAS" in texto_eco[0]
    assert "EVALUACION DE FLUJOS POR DOPPLER" in texto_eco[0]
    assert "CONCLUSIONES" in texto_eco[1]
    assert "Pagina 2 de 2" in texto_eco[1]
    assert texto_eco[0].index("VALVULAS CARDIACAS") < texto_eco[0].index("EVALUACION DE FLUJOS POR DOPPLER")
    ecocardiograma.close()


def test_corpus_identifica_datos_ficticios_y_no_requiere_red(tmp_path, monkeypatch) -> None:
    def red_prohibida(*_args, **_kwargs):
        raise AssertionError("El generador sintetico no debe abrir conexiones de red")

    monkeypatch.setattr(socket, "create_connection", red_prohibida)
    corpus = generar_corpus_clinico(tmp_path, semilla=23)
    identidad = _identidad_de_semilla(23)
    textos = []
    for documento_sintetico in corpus.documentos:
        documento = pymupdf.open(documento_sintetico.ruta)
        textos.extend(pagina.get_text("text", sort=True) for pagina in documento)
        documento.close()

    contenido = "\n".join(textos)
    assert "DOCUMENTO SINTETICO - SOLO PRUEBAS" in contenido
    assert identidad.nombre_lab in contenido
    assert identidad.dni not in str(corpus.oraculo)


def test_corpus_conserva_campos_y_secciones_contractuales_de_cada_origen(tmp_path) -> None:
    """Contrato de campos/secciones que cada parser real necesita encontrar
    literalmente -- ver `tests/fixtures/matriz_cobertura_sinteticos.md`.

    Las cadenas de abajo se leyeron directamente del fixture parseable real
    versionado (`tests/fixtures/parseables/{tipo}-01.txt`), no del generador
    hand-typed anterior: acentos/símbolos exactos (p. ej. "Nº Petición:",
    "F.Nacimiento :") importan porque son justamente lo que el regex del
    parser real espera -- ver `plantilla_documento.py`.
    """
    corpus = generar_corpus_clinico(tmp_path, semilla=29)
    rutas = {documento.tipo: documento.ruta for documento in corpus.documentos}

    def texto_de(ruta):
        documento = pymupdf.open(ruta)
        texto = "\n".join(pagina.get_text("text", sort=True) for pagina in documento)
        documento.close()
        return texto

    contratos = {
        "ecg": (
            "MORTARA",
            "12SL",
            "~,",
            "ID:",
            "yr)",
            "Male",
            "Technician:",
            "Test ind:",
            "Ordered by:",
            "Vent. rate",
            "PR interval",
            "QRS duration",
            "QT/QTc",
            "P-R-T axes",
            "PID / NAME MISMATCH",
            "25 mm/s",
            "10 mm/mV",
            "40 Hz",
        ),
        "laboratorio": (
            "Apellido y Nombre:",
            "DNI:",
            "F.Nacimiento :",
            "Edad:",
            "Médico:",
            "Nº Petición:",
            "Fecha:",
            "Hora de Extracción:",
            "Origen:",
            "HEMATOLOGIA",
            "HEMOSTASIA",
            "QUÍMICA CLÍNICA",
            "IONOGRAMA",
        ),
        "ecocardiograma": (
            "PACIENTE:",
            "Documento:",
            "Nº ESTUDIO:",
            "Fecha Estudio:",
            "Medico Solicitante:",
            "Peso:",
            "Altura:",
            "S.C.",
            "MEDIDAS",
            "MOTILIDAD SEGMENTARIA",
            "AURICULAS",
            "VALVULAS CARDIACAS",
            "AORTICA",
            "MITRAL",
            "TRICUSPIDEA",
            "PULMONAR",
            "PERICARDIO",
            "EVALUACION DE FLUJOS POR DOPPLER",
            "FLUJO AORTICO",
            "FLUJO MITRAL",
            "FLUJO PULMONAR",
            "FLUJO TRICUSPIDEO",
            "CONCLUSIONES",
            "Matrícula",
            "DIAGNOSTICO POR IMAGENES",
        ),
    }

    for tipo, campos in contratos.items():
        texto = texto_de(rutas[tipo])
        faltantes = [campo for campo in campos if campo not in texto]
        assert not faltantes, f"'{tipo}' no reproduce: {faltantes}"

    texto_laboratorio = texto_de(rutas["laboratorio"])
    assert texto_laboratorio.index("HEMATOLOGIA") < texto_laboratorio.index("HEMOSTASIA")
    assert texto_laboratorio.index("HEMOSTASIA") < texto_laboratorio.index("QUÍMICA CLÍNICA")
    assert texto_laboratorio.index("QUÍMICA CLÍNICA") < texto_laboratorio.index("IONOGRAMA")
