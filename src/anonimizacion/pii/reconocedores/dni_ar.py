"""Reconocedor custom de DNI argentino: Presidio no trae uno built-in. Combina regex de
forma (6-8 dígitos, con o sin puntos) con validación semántica de rango en `validate_result`."""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

ENTIDAD_DNI_AR = "DNI_AR"

# Piso bajado de 7 a 6 cifras para no descartar DNIs viejos sin cero a la izquierda.
# Invariante: «Piso de dígitos del DNI» (Obsidian, Invariantes medidos).
_DNI_MINIMO = 100_000
_DNI_MAXIMO = 99_999_999

# `(?<![\d.])`/`(?!\d)` evitan matchear un sub-grupo dentro de una secuencia de puntos mal
# agrupada, sin invalidar por un punto final de oración (separador de miles es ambiguo).
_PATRONES = [
    Pattern(
        name="dni_con_puntos",
        regex=r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}(?!\d)",
        score=0.85,
    ),
    Pattern(
        # DNI viejo de 6 cifras con puntos: mismo agrupamiento de a tres, sin el primer grupo de 1-2 dígitos.
        name="dni_con_puntos_seis_digitos",
        regex=r"(?<![\d.])\d{3}\.\d{3}(?!\d)",
        score=0.85,
    ),
    Pattern(
        name="dni_sin_puntos",
        regex=r"(?<!\d)\d{6,8}(?!\d)",
        score=0.5,  # sin separador es ambiguo con otros números de 6-8 dígitos
    ),
]


class ReconocedorDniAr(PatternRecognizer):
    """`PatternRecognizer` de Presidio para el formato de DNI argentino."""

    def __init__(self) -> None:
        super().__init__(
            supported_entity=ENTIDAD_DNI_AR,
            patterns=_PATRONES,
            supported_language="es",
            name="ReconocedorDniAr",
        )

    def validate_result(self, pattern_text: str) -> bool | None:
        """Valida formato (dígitos, 6-8 cifras, en rango). Devuelve `False` para invalidar o
        `None` si es válido -- nunca `True`, para no pisar el puntaje diferencial del patrón."""
        limpio = pattern_text.replace(".", "")
        if not limpio.isdigit() or len(limpio) not in (6, 7, 8):
            return False
        if not (_DNI_MINIMO <= int(limpio) <= _DNI_MAXIMO):
            return False
        return None
