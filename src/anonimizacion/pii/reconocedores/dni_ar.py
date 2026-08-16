"""Reconocedor custom de DNI argentino (spec `pii-detection`).

Presidio no trae un reconocedor built-in para el formato de DNI argentino
(7-8 dígitos, con o sin puntos como separador de miles: `12.345.678` o
`12345678`). Este módulo registra un `PatternRecognizer` propio -Presidio
está diseñado justamente para eso- que combina una regex de forma con una
validación semántica de rango en `validate_result`: no cualquier número de
7-8 cifras es un DNI válido, así que además de matchear el patrón se valida
que el valor entero caiga dentro del rango de DNIs argentinos realmente
emitidos (aprox. 1.000.000 a 99.999.999; por debajo de eso son numeraciones
muy antiguas fuera de uso práctico en este corpus, por encima el rango de
7-8 dígitos ya no alcanza).
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

ENTIDAD_DNI_AR = "DNI_AR"

_DNI_MINIMO = 1_000_000
_DNI_MAXIMO = 99_999_999

# `(?<![\d.])` al inicio evita matchear un sub-grupo dentro de una secuencia
# de puntos más larga y mal agrupada (p.ej. "1.2.345.678" no debe matchear
# "2.345.678"). Al final alcanza con `(?!\d)`: rechazar dígito extiende
# correctamente el número, pero un punto final es ambiguo (separador de
# miles vs. punto de fin de oración) y NO se debe usar para invalidar, si no
# "DNI: 12.345.678." (con punto final de oración) dejaría de matchear.
_PATRONES = [
    Pattern(
        name="dni_con_puntos",
        regex=r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}(?!\d)",
        score=0.85,
    ),
    Pattern(
        name="dni_sin_puntos",
        regex=r"(?<!\d)\d{7,8}(?!\d)",
        score=0.5,  # sin separador es ambiguo con otros números de 7-8 dígitos
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
        """Valida formato: solo dígitos (tras sacar puntos), 7-8 cifras, en rango.

        Devuelve `False` para invalidar (puntaje a 0, se descarta), o `None`
        cuando el formato es válido -- Presidio interpreta `True` como
        "validado, puntaje a 1.0", lo que borraría a propósito la diferencia
        de confianza entre el patrón con puntos (0.85, forma inequívoca) y
        sin puntos (0.5, ambiguo con cualquier otro número de 7-8 cifras);
        `None` deja el puntaje del patrón que efectivamente matcheó.
        """
        limpio = pattern_text.replace(".", "")
        if not limpio.isdigit() or len(limpio) not in (7, 8):
            return False
        if not (_DNI_MINIMO <= int(limpio) <= _DNI_MAXIMO):
            return False
        return None
