from __future__ import annotations

import socket

import pymupdf

from tests.fixtures.pdf_sintetico import generar_corpus_clinico


def test_corpus_con_misma_semilla_repite_oraculo_y_tres_tipos(tmp_path) -> None:
    primero = generar_corpus_clinico(tmp_path / "uno", semilla=7)
    segundo = generar_corpus_clinico(tmp_path / "dos", semilla=7)

    assert primero.oraculo == segundo.oraculo
    assert {documento.tipo for documento in primero.documentos} == {"ecg", "laboratorio", "ecocardiograma"}
    assert all(documento.ruta.read_bytes().startswith(b"%PDF") for documento in primero.documentos)


def test_corpus_usa_pii_sintetica_y_no_la_expone_en_oraculo(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=9)

    contenido = "\n".join(pymupdf.open(documento.ruta)[0].get_text() for documento in corpus.documentos)
    assert "Paciente Sintetico" in contenido
    assert "Paciente Sintetico" not in str(corpus.oraculo)
    assert all("dni" not in claves for claves in corpus.oraculo.values())


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
    assert "Resultado" in texto_laboratorio[0]
    assert "Unidades" in texto_laboratorio[0]
    assert "Valores de Referencia" in texto_laboratorio[0]
    assert "QUIMICA CLINICA" in texto_laboratorio[1]
    assert "Pagina 3 de 3" in texto_laboratorio[2]
    assert texto_laboratorio[0].index("HEMATOLOGIA") < texto_laboratorio[0].index("Resultado")
    laboratorio.close()

    ecocardiograma = pymupdf.open(rutas["ecocardiograma"])
    assert len(ecocardiograma) == 2
    assert all((round(pagina.rect.width), round(pagina.rect.height)) == (616, 862) for pagina in ecocardiograma)
    texto_eco = [pagina.get_text("text", sort=True) for pagina in ecocardiograma]
    assert "ECOCARDIOGRAMA DOPPLER" in texto_eco[0]
    assert "DDVI" in texto_eco[0]
    assert "MOTILIDAD SEGMENTARIA" in texto_eco[0]
    assert "VALVULAS" in texto_eco[1]
    assert "DOPPLER" in texto_eco[1]
    assert "CONCLUSIONES" in texto_eco[1]
    assert "Pagina 2 de 2" in texto_eco[1]
    assert texto_eco[1].index("VALVULAS") < texto_eco[1].rindex("DOPPLER") < texto_eco[1].index("CONCLUSIONES")
    ecocardiograma.close()


def test_corpus_identifica_datos_ficticios_y_no_requiere_red(tmp_path, monkeypatch) -> None:
    def red_prohibida(*_args, **_kwargs):
        raise AssertionError("El generador sintetico no debe abrir conexiones de red")

    monkeypatch.setattr(socket, "create_connection", red_prohibida)
    corpus = generar_corpus_clinico(tmp_path, semilla=23)
    textos = []
    for documento_sintetico in corpus.documentos:
        documento = pymupdf.open(documento_sintetico.ruta)
        textos.extend(pagina.get_text("text", sort=True) for pagina in documento)
        documento.close()

    contenido = "\n".join(textos)
    assert "DOCUMENTO SINTETICO - SOLO PRUEBAS" in contenido
    assert "Paciente Sintetico" in contenido
    assert "Paciente Sintetico" not in str(corpus.oraculo)


def test_corpus_conserva_campos_y_secciones_contractuales_de_cada_origen(tmp_path) -> None:
    corpus = generar_corpus_clinico(tmp_path, semilla=29)
    rutas = {documento.tipo: documento.ruta for documento in corpus.documentos}

    def texto_de(ruta):
        documento = pymupdf.open(ruta)
        texto = "\n".join(pagina.get_text("text", sort=True) for pagina in documento)
        documento.close()
        return texto

    contratos = {
        "ecg": (
            "12SL",
            "Paciente:",
            "PID:",
            "Fecha:",
            "Age:",
            "Sex:",
            "Technician:",
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
            "Fecha de Nacimiento:",
            "Edad:",
            "Medico Derivante:",
            "Nro. de Peticion:",
            "Fecha:",
            "Hora de Extraccion:",
            "Origen:",
            "Determinacion",
            "Resultado",
            "Unidades",
            "Valores de Referencia",
            "HEMATOLOGIA",
            "HEMOSTASIA",
            "QUIMICA CLINICA",
            "IONOGRAMA",
        ),
        "ecocardiograma": (
            "Paciente:",
            "Documento:",
            "Nro. de Estudio:",
            "Fecha:",
            "Medico Solicitante:",
            "Peso:",
            "Altura:",
            "Superficie Corporal:",
            "FA",
            "Septum",
            "P. Posterior",
            "MOTILIDAD SEGMENTARIA",
            "VALVULA MITRAL",
            "VALVULA AORTICA",
            "VALVULA TRICUSPIDEA",
            "VALVULA PULMONAR",
            "PERICARDIO",
            "DOPPLER",
            "CONCLUSIONES",
            "Medico Informante:",
            "Matricula:",
        ),
    }

    for tipo, campos in contratos.items():
        texto = texto_de(rutas[tipo])
        assert all(campo in texto for campo in campos)

    texto_laboratorio = texto_de(rutas["laboratorio"])
    assert texto_laboratorio.index("HEMATOLOGIA") < texto_laboratorio.index("HEMOSTASIA")
    assert texto_laboratorio.index("HEMOSTASIA") < texto_laboratorio.index("QUIMICA CLINICA")
    assert texto_laboratorio.index("QUIMICA CLINICA") < texto_laboratorio.index("IONOGRAMA")
