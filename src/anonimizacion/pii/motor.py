"""Motor central de detección de PII, 100% offline: NER de Presidio+spaCy sobre texto libre
y header, más `ReconocedorDniAr` custom. Nunca descarta por puntaje bajo, sólo marca `baja_confianza`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from anonimizacion.pii.reconocedores.dni_ar import ReconocedorDniAr

IDIOMA = "es"
MODELO_SPACY_ES = "es_core_news_lg"
ENTIDAD_ID_INTERNO = "ID_INTERNO"

# Deja fuera al DNI sin puntos (0.5, ambiguo) pero dentro al DNI con puntos y al NER (0.85).
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
        """Marca IDs internos ya conocidos (Nº Petición/Estudio) como cuasi-identificadores: no
        identifican solos pero combinados con institución+fecha sí re-identifican, sin pasar por NER/regex."""
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
