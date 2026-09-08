"""Reconocedor custom de DNI argentino (spec `pii-detection`).

Presidio no trae un reconocedor built-in para el formato de DNI argentino
(6-8 dígitos, con o sin puntos como separador de miles: `12.345.678`,
`987.654` o `12345678`). Este módulo registra un `PatternRecognizer` propio
-Presidio está diseñado justamente para eso- que combina una regex de forma
con una validación semántica de rango en `validate_result`: no cualquier
número de 6-8 cifras es un DNI válido, así que además de matchear el patrón
se valida que el valor entero caiga dentro del rango de DNIs argentinos
realmente emitidos.

**Piso de 6 dígitos, no 7 (revisión Tarea 3, evidencia real del dominio)**:
el piso original (`_DNI_MINIMO = 1_000_000`, el menor entero de 7 cifras)
descartaba cualquier DNI de 6 dígitos. Eso es un hueco de fuga real: los DNI
más viejos (personas de edad avanzada, mayoría de la población en un
servicio de cardiología) tienen 6 dígitos sin cero a la izquierda -- no es
un caso de borde exótico en este dominio. `canonicalizar_dni`
(`pseudonimizacion/claves.py`) ya acepta cualquier longitud (solo hace
`lstrip("0")`), así que con el piso viejo la canonicalización aceptaba un
DNI de 6 dígitos pero la detección lo descartaba: un DNI real de un
paciente añoso mencionado en texto libre se hubiera publicado sin redactar.
Bajar el piso a 6 dígitos (`_DNI_MINIMO = 100_000`) cierra esa incoherencia.

Evidencia de que bajar el piso no dispara falsos positivos masivos sobre
los números clínicos de este corpus: los tres tipos de documento producen
números de 6-8 dígitos en dos lugares nada más -- `Nº Petición` (7 dígitos,
laboratorio) y `Nº Estudio` (6 dígitos, eco) -- y NINGUNO de los dos pasa
nunca por este reconocedor: ambos se leen directo del header a
`IdentidadCruda.ids_internos` y se clasifican como cuasi-identificador vía
`MotorPii.evaluar_ids_internos` (`pii/motor.py`), sin pasar por NER ni por
este regex (ver `pii/politica.py::_cuasi_identificadores`). Los valores que
sí se escanean con este reconocedor son: (a) el texto libre dictado de
`ContenidoEco.secciones_texto` y (b) valores logueados por
`observabilidad/bitacora_segura.py`. Ninguno de los dos contiene mediciones
clínicas de 6+ dígitos -- las mediciones ecocardiográficas se expresan en
mm/porcentaje (2-3 cifras) y los resultados de laboratorio son valores como
concentraciones o conteos (típicamente ≤4 cifras) -- así que el único
número real de 6+ cifras que podría aparecer ahí es, en el peor caso, un ID
interno mencionado por error en la conclusión dictada, que de todos modos
es un cuasi-identificador: sobre-redactarlo no es una fuga (spec: el riesgo
real es nombre/DNI, no cuasi-identificadores) y si en cambio fuera el DNI
real de un paciente añoso, dejarlo de detectar sí lo sería. Con ese
trade-off medido, bajar el piso es la decisión correcta.
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

ENTIDAD_DNI_AR = "DNI_AR"

_DNI_MINIMO = 100_000  # menor entero de 6 cifras (ver docstring del módulo)
_DNI_MAXIMO = 99_999_999

# `(?<![\d.])` al inicio evita matchear un sub-grupo dentro de una secuencia
# de puntos más larga y mal agrupada (p.ej. "1.2.345.678" no debe matchear
# "2.345.678", ni "1.234.567" debe matchear como si fuera "234.567" de 6
# cifras). Al final alcanza con `(?!\d)`: rechazar dígito extiende
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
        # DNI viejo de 6 cifras agrupado con puntos ("987.654"): mismo
        # agrupamiento de a tres desde la derecha que el de 7-8 cifras, pero
        # sin el primer grupo de 1-2 dígitos.
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
        """Valida formato: solo dígitos (tras sacar puntos), 6-8 cifras, en rango.

        Devuelve `False` para invalidar (puntaje a 0, se descarta), o `None`
        cuando el formato es válido -- Presidio interpreta `True` como
        "validado, puntaje a 1.0", lo que borraría a propósito la diferencia
        de confianza entre el patrón con puntos (0.85, forma inequívoca) y
        sin puntos (0.5, ambiguo con cualquier otro número de 6-8 cifras);
        `None` deja el puntaje del patrón que efectivamente matcheó.
        """
        limpio = pattern_text.replace(".", "")
        if not limpio.isdigit() or len(limpio) not in (6, 7, 8):
            return False
        if not (_DNI_MINIMO <= int(limpio) <= _DNI_MAXIMO):
            return False
        return None
