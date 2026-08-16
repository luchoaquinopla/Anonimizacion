"""Motor central de detección de PII (spec `pii-detection`).

Combina dos fuentes de detección, 100% offline (sin llamadas de red en
`detectar`/`evaluar_ids_internos`; el único costo de red es la descarga
*previa* del modelo spaCy, hecha una vez fuera de la suite de tests):

1. NER de Presidio sobre spaCy `es_core_news_lg` (nombres de persona,
   ubicaciones, fechas, etc. en texto libre en español) — cubre PII NO
   estructurada, como un nombre mencionado dentro de la conclusión dictada
   de un eco (ver design.md, decisión 6: la detección corre también sobre
   texto libre, no solo headers).
2. `ReconocedorDniAr`, un `PatternRecognizer` custom (`reconocedores/dni_ar.py`)
   registrado en el motor: Presidio no conoce el formato de DNI argentino de
   fábrica.

Dos conceptos de dominio que este módulo modela explícitamente:

- **Cuasi-identificador**: un ID interno (Nº Petición, Nº Estudio, ID
  interno de ECG) no es PII directa por sí solo -no identifica a nadie por
  su propio valor, a diferencia de un DNI o un nombre- pero combinado con
  otros datos (institución + fecha + ese número) puede volver a identificar
  a un paciente. `evaluar_ids_internos` los marca con `cuasi_identificador=True`
  para que la política aguas abajo (`pii/politica.py`) decida un tratamiento
  distinto al de una detección directa (DNI/nombre).
- **Baja confianza marcada, no descartada**: en este pipeline un falso
  negativo (PII no detectada) es mucho peor que un falso positivo -el dato
  termina en el dataset de entrenamiento sin anonimizar-, así que ninguna
  detección se descarta por tener puntaje bajo. En cambio se marca con
  `baja_confianza=True` para que la política aguas abajo pueda, por ejemplo,
  anonimizar igual pero con menos agresividad de log/alerta, o enrutar a
  revisión. El umbral (`UMBRAL_BAJA_CONFIANZA`) es deliberadamente conservador.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from anonimizacion.pii.reconocedores.dni_ar import ReconocedorDniAr

IDIOMA = "es"
MODELO_SPACY_ES = "es_core_news_lg"
ENTIDAD_ID_INTERNO = "ID_INTERNO"

# Puntaje mínimo para considerar una detección de "alta" confianza. Por
# debajo se marca `baja_confianza=True` (nunca se descarta, ver docstring
# del módulo). 0.6 deja fuera al DNI sin separador de miles (score 0.5,
# ambiguo con cualquier otro número de 7-8 dígitos) pero mantiene dentro al
# DNI con puntos (0.85) y a las entidades NER de spaCy (PERSON/LOCATION 0.85).
UMBRAL_BAJA_CONFIANZA = 0.6


@dataclass(frozen=True)
class DeteccionPii:
    """Una detección de PII: qué tipo, dónde y con qué certeza."""

    tipo_entidad: str
    inicio: int
    fin: int
    puntaje: float
    baja_confianza: bool
    cuasi_identificador: bool = False


def _crear_analizador(modelo_spacy: str) -> AnalyzerEngine:
    proveedor = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": IDIOMA, "model_name": modelo_spacy}],
        }
    )
    motor_nlp = proveedor.create_engine()
    analizador = AnalyzerEngine(nlp_engine=motor_nlp, supported_languages=[IDIOMA])
    analizador.registry.add_recognizer(ReconocedorDniAr())
    return analizador


class MotorPii:
    """Motor híbrido NER (Presidio+spaCy) + regex DNI custom, 100% offline."""

    def __init__(self, modelo_spacy: str = MODELO_SPACY_ES) -> None:
        self._modelo_spacy = modelo_spacy
        self._analizador = _crear_analizador(modelo_spacy)

    def detectar(self, texto: str) -> tuple[DeteccionPii, ...]:
        """Escanea texto libre o de header en busca de PII directa (nombre, DNI, etc.)."""
        resultados = self._analizador.analyze(text=texto, language=IDIOMA)
        return tuple(
            DeteccionPii(
                tipo_entidad=resultado.entity_type,
                inicio=resultado.start,
                fin=resultado.end,
                puntaje=resultado.score,
                baja_confianza=resultado.score < UMBRAL_BAJA_CONFIANZA,
            )
            for resultado in resultados
        )

    def evaluar_ids_internos(self, ids_internos: Sequence[str]) -> tuple[DeteccionPii, ...]:
        """Marca IDs internos ya conocidos (Nº Petición/Estudio) como cuasi-identificadores.

        No pasan por NER/regex: ya sabemos que son IDs (vienen tipados de
        `IdentidadCruda.ids_internos`), no hay incertidumbre de detección que
        marcar como baja confianza.
        """
        return tuple(
            DeteccionPii(
                tipo_entidad=ENTIDAD_ID_INTERNO,
                inicio=0,
                fin=len(id_interno),
                puntaje=1.0,
                baja_confianza=False,
                cuasi_identificador=True,
            )
            for id_interno in ids_internos
        )
