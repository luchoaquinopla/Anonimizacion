"""Test de regresión de PARSEO contra los fixtures parseables versionados
(Tarea "fixture parseable de esqueletos reales", `tests/fixtures/parseables/`).

Complementa a `tests/deteccion/test_centinela_esqueletos.py`: aquel centinela
sólo puede afirmar DETECCIÓN DE TIPO y ESTABILIDAD DE LAYOUT porque el
esqueleto enmascarado tapa todos los valores por forma (`X`/`0`). Los
fixtures de este módulo (`generar_fixture_parseable`, ver `esqueleto.py`)
reemplazan cada valor por un sustituto SINTÉTICO plausible de la MISMA
forma -- suficiente para que los TRES parsers reales de `parseo/` los
procesen de punta a punta, sin excepción, y esto SÍ puede afirmar algo
sobre parseo real.

DISEÑO CRÍTICO -- por qué los números de abajo están hardcodeados: al igual
que `test_centinela_esqueletos.py`, las expectativas (cantidad de
resultados, medidas, secciones, valores puntuales) NO se leen del propio
fixture ni se recalculan en el momento a partir de constantes "vivas". Se
midieron UNA vez contra la corrida real (`generar_fixture_parseable` sobre
los PDFs reales del instituto) y se pegan acá como literales. Si el test
leyera sus propias expectativas del resultado de la corrida, un parser roto
seguiría en verde para siempre: cualquier regresión se "grabaría" como el
nuevo comportamiento esperado en vez de hacer fallar el test -- exactamente
la trampa que este test existe para evitar.

Nota sobre los NOMBRES/PALABRAS que aparecen en las aserciones puntuales de
abajo (secciones, nombres de prueba/medida): son palabras SINTÉTICAS
generadas por `_sustituir_letras` (determinísticas mediante hash, ver
`esqueleto.py`) -- no tienen ningún significado clínico ni identifican a
nadie. Lo único que importa de ellas es que su FORMA (longitud, mayúsculas)
y su ROL estructural (sección, nombre de prueba) se preserven exactamente
igual corrida tras corrida, porque los fixtures son estáticos y la
sustitución es determinística.
"""

from __future__ import annotations

from pathlib import Path

from anonimizacion.parseo.ecg_mortara import ParseadorEcgMortara
from anonimizacion.parseo.eco_doppler import ParseadorEcoDoppler
from anonimizacion.parseo.laboratorio_general import ParseadorLaboratorioGeneral
from tests.fixtures.lectura_fixture_texto import leer_texto_extraido_de_fixture

_DIRECTORIO_PARSEABLES = Path(__file__).parent.parent / "fixtures" / "parseables"


def test_laboratorio_parsea_el_fixture_real_sin_excepcion_y_extrae_36_resultados() -> None:
    texto = leer_texto_extraido_de_fixture(_DIRECTORIO_PARSEABLES / "laboratorio-01.txt")

    documento = ParseadorLaboratorioGeneral().parsear(texto)  # no debe lanzar ErrorParseo

    assert len(documento.contenido.resultados) == 36
    assert {resultado.seccion for resultado in documento.contenido.resultados} == {
        "HEMATOLOGIA",
        "BEJUZAQAB",
        "HEMOSTASIA",
        "QUIMICA CLINICA",
        "IONOGRAMA POBIGA",
        "DUGIJUW IQAJIZAYUKAC",
    }
    # Campos de header poblados -- estructura completa, no sólo nombre/fecha.
    assert documento.identidad.dni is not None
    assert documento.identidad.fecha_nac is not None
    assert documento.contenido.numero_peticion != ""
    assert sorted(documento.adicionales.keys()) == ["edad", "medico_derivante", "origen"]
    # Valor puntual con su unidad: se nota si un cambio de columna corrompe
    # el mapeo resultado/unidad/rango del formato real (2+ espacios).
    primero = documento.contenido.resultados[0]
    assert (primero.resultado, primero.unidades, primero.valores_referencia) == ("3", "mm/hora", "9 - 32")


def test_eco_doppler_parsea_el_fixture_real_sin_excepcion_y_extrae_10_medidas_y_12_secciones() -> None:
    texto = leer_texto_extraido_de_fixture(_DIRECTORIO_PARSEABLES / "eco-01.txt")

    documento = ParseadorEcoDoppler().parsear(texto)  # no debe lanzar ErrorParseo

    assert len(documento.contenido.medidas) == 10
    assert len(documento.contenido.secciones_texto) == 12
    assert [seccion.nombre for seccion in documento.contenido.secciones_texto] == [
        "MOTILIDAD SEGMENTARIA",
        "AURICULAS",
        "VALVULAS CARDIACAS - AORTICA",
        "VALVULAS CARDIACAS - MITRAL",
        "VALVULAS CARDIACAS - PULMONAR",
        "VALVULAS CARDIACAS - TRICUSPIDEA",
        "PERICARDIO",
        "EVALUACION DE FLUJOS POR DOPPLER - FLUJO AORTICO",
        "EVALUACION DE FLUJOS POR DOPPLER - FLUJO MITRAL",
        "EVALUACION DE FLUJOS POR DOPPLER - FLUJO PULMONAR",
        "EVALUACION DE FLUJOS POR DOPPLER - FLUJO TRICUSPIDEO",
        "CONCLUSIONES",
    ]
    # La firma del médico informante depende de reconocer "Matrícula" sin
    # etiqueta explícita (ver `eco_doppler.py`) -- si se rompe, `firma`
    # vuelve a `None` silenciosamente.
    assert documento.contenido.firma is not None
    assert documento.contenido.firma.matricula == "N 2736"
    assert documento.identidad.dni is not None
    assert sorted(documento.adicionales.keys()) == ["altura", "edad", "peso", "superficie_corporal"]
    # Valor puntual con su unidad.
    primera = documento.contenido.medidas[0]
    assert (primera.valor, primera.unidad) == ("81", "mm")


def test_ecg_mortara_parsea_el_fixture_real_sin_excepcion_y_extrae_las_5_medidas() -> None:
    texto = leer_texto_extraido_de_fixture(_DIRECTORIO_PARSEABLES / "ecg-01.txt")

    documento = ParseadorEcgMortara().parsear(texto)  # no debe lanzar ErrorParseo

    contenido = documento.contenido
    assert (contenido.vent_rate, contenido.pr_interval, contenido.qrs_duration, contenido.qt_qtc, contenido.ejes) == (
        "49",
        "351",
        "611",
        "708/225",
        "88 64 29",
    )
    # Fecha de nacimiento presente -- exige que el sufijo "yr" sobreviva
    # literal junto a la fecha (ver `esqueleto.py`, `_ETIQUETAS_MEDIDA_ECG`).
    assert documento.identidad.fecha_nac is not None
    assert documento.identidad.dni is None  # el ECG nunca trae DNI (ver design.md)
    assert sorted(documento.adicionales.keys()) == ["edad", "institucion", "medico_derivante", "tecnico", "test_ind"]
