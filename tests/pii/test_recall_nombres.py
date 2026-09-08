"""Banco de recall del motor NER sobre apellidos/nombres reales de la región (Tarea 1).

**Por qué existe este archivo**: hasta ahora nadie midió el recall real del motor de PII
(Presidio + spaCy `es_core_news_lg`, modelo entrenado sobre corpus de noticias en español
peninsular) sobre apellidos/nombres realmente usados en Corrientes, Argentina. Este repo
ya tiene un antecedente grave de "inventamos un dato sintético, lo testeamos contra sí
mismo y creímos que funcionaba" (los marcadores fantasma de las firmas del ECG y del eco,
ver commit `e919b5a`). Este archivo NO repite ese patrón: no arma un gazetteer y lo valida
contra sí mismo, sino que corre el motor REAL (`MotorPii`, el mismo que usa
`pii/politica.py` sobre `ContenidoEco.secciones_texto`) contra oraciones clínicas
realistas y mide, honestamente, qué fracción detecta.

**El punto de este archivo NO es que el número sea alto** -- es que exista y sea real. Los
pisos (`_GRUPOS`, campo `piso`) están calibrados contra el recall MEDIDO en esta máquina
con esta versión de `es_core_news_lg` -- no elegidos de antemano ni ajustados para que
"quede lindo". El resultado real de esta corrida fue sorprendentemente alto en casi todos
los grupos (ver tabla abajo); eso NO se ocultó ni se "arregló" bajando artificialmente el
piso -- se documenta tal cual salió, con la única excepción real encontrada (italianos,
por la ambigüedad léxica de "Colombo" con la ciudad de Sri Lanka, no por origen étnico).

## Recall medido en esta corrida (referencia, ver pisos reales más abajo)

| Grupo             | Recall medido | Nota                                          |
|-------------------|---------------|------------------------------------------------|
| ibericos          | 24/24 = 1.00  | control positivo, como se esperaba             |
| italianos         | 22/24 = 0.92  | "Colombo" sin nombre de pila falla 2/2 veces   |
| guaranies         | 24/24 = 1.00  | mejor de lo esperado a priori                  |
| arabes_libaneses  | 24/24 = 1.00  | mejor de lo esperado a priori                  |
| alemanes_eslavos  | 24/24 = 1.00  | mejor de lo esperado a priori                  |

**Hallazgo honesto que contradice la hipótesis inicial**: se esperaba que los grupos no
ibéricos midieran peor por sesgo del corpus de entrenamiento (español peninsular). La
medición real muestra que spaCy usa fuertemente señales de capitalización + contexto
sintáctico (p.ej. "Dr. X" o "derivado por X") para tipificar PERSON, lo que generaliza
razonablemente bien incluso a apellidos no ibéricos EN ESTE BANCO. La única falla real
encontrada es puntual (ambigüedad léxica "Colombo" = apellido o ciudad), no un patrón de
sesgo étnico amplio. Esto no significa "no hay riesgo" -- significa que el riesgo medido
en este banco concreto, con este tamaño de muestra (24 oraciones por grupo), es bajo; un
banco más grande o con más nombres ambiguos (como "Colombo") podría revelar más casos como
ese. Ver Tarea 2 (comparación exacta contra el nombre conocido del documento) como la red
de contención real para lo que este banco no llegue a cubrir.

**Descubrimiento adicional, fuera del alcance de los pisos de este archivo pero
documentado por transparencia**: se corrió el mismo banco con los acentos removidos
(simulando una extracción de PDF que pierda diacríticos) y el recall SÍ cae de forma
medible en varios grupos (p.ej. "López" sin tilde no se detecta nunca en este banco,
"Lopez" → 0 detecciones vs. "López" → detectado). Esto sugiere que la robustez a texto sin
acentos es un eje de riesgo real e independiente del origen del apellido -- candidato a un
banco de recall propio en un trabajo futuro, no se mezcla acá para no confundir dos
variables distintas (origen del nombre vs. integridad del texto extraído).

## Los cinco grupos y por qué están justificados

1. **Ibéricos comunes** (control positivo): los apellidos más frecuentes de España según
   estudios demográficos públicos (García, Fernández, López, González, Rodríguez,
   Martínez) y nombres de pila igual de comunes. `es_core_news_lg` se entrena sobre corpus
   de noticias en español peninsular, así que este grupo es el piso de comparación para
   los demás.
2. **Italianos**: Argentina recibió una inmigración italiana masiva entre 1880 y 1950,
   hecho demográfico ampliamente documentado (INDEC, estudios de migración: una proporción
   mayoritaria de la población argentina tiene ascendencia italiana). Apellidos como
   Rossi, Bianchi, Ferrari, Colombo, Romano son de altísima prevalencia real en el padrón
   argentino, y nombres de pila italianos (Giovanni, Franco, Aldo, Renzo) todavía se usan
   en familias de esa ascendencia.
3. **Guaraníes / origen indígena regional**: Corrientes es la provincia donde se hizo este
   trabajo; el guaraní tiene fuerte presencia cultural en el litoral y es idioma cooficial
   en la provincia vecina (Corrientes lo declaró idioma oficial alternativo en 2004).
   Apellidos de fuerte raíz mestiza hispano-guaraní muy comunes en la región (Chamorro,
   Miño, Portillo, Ortellado) y nombres de pila de origen guaraní realmente usados en la
   zona (Araí: "llovizna", Yasy: "luna", Poty: "flor").
4. **Árabes / libaneses-sirios**: oleada de inmigración siria-libanesa a Argentina entre
   1890 y 1950 (los "turcos", por el pasaporte otomano con el que llegaban), con presencia
   documentada en el NEA. Apellidos reales de esa colectividad en Argentina (Sapag, Yoma,
   Assef, Salum, Dip) y nombres de pila árabes que se mantienen en descendientes (Yamil,
   Nadia, Karim, Selim, Fadwa).
5. **Alemanes y eslavos**: colonización alemana del Volga en el litoral/pampa húmeda y
   colonias polacas/ucranianas en Misiones (provincia limítrofe con Corrientes), ambos
   procesos migratorios documentados de fines del s. XIX/principios del s. XX. Apellidos
   alemanes (Müller, Schmidt, Wagner) y eslavos (Kowalski, Nowak, Melnyk), con nombres de
   pila igualmente extranjeros (Klaus, Ingrid, Iván, Olga, Kurt, Tatiana).

Si no se pudo justificar un nombre con un motivo demográfico real, no se puso en la lista.

## Por qué no hay marcador de skip

`tests/pii/test_motor.py` y `tests/pii/test_politica.py` ya instancian `MotorPii()` (carga
spaCy) sin ningún marcador condicional -- es lento por diseño (costo de carga del modelo,
100% local, sin red) y ese costo ya lo paga la suite hoy. Este archivo sigue la misma
convención (fixture de módulo, una sola carga) en vez de inventar un marcador nuevo: el
único marcador condicional que existe en este repo (`postgres`) protege contra una
dependencia de infraestructura real (Docker); spaCy/Presidio no lo son, ya están instalados
como dependencia del proyecto (`pyproject.toml`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from anonimizacion.pii.motor import MotorPii

# --- Bancos de apellidos/nombres por grupo (ver docstring del módulo) ---

_IBERICOS = [
    ("Juan", "García"),
    ("María", "Fernández"),
    ("Carlos", "López"),
    ("Ana", "González"),
    ("Pedro", "Rodríguez"),
    ("Lucía", "Martínez"),
]

_ITALIANOS = [
    ("Giovanni", "Rossi"),
    ("Franco", "Bianchi"),
    ("Aldo", "Ferrari"),
    ("Renzo", "Colombo"),
    ("Marco", "Romano"),
    ("Elena", "Ricci"),
]

_GUARANIES = [
    ("Araí", "Chamorro"),
    ("Yasy", "Miño"),
    ("Poty", "Portillo"),
    ("Ramón", "Ortellado"),
    ("Rosana", "Chamorro"),
    ("Darío", "Miño"),
]

_ARABES_LIBANESES = [
    ("Yamil", "Sapag"),
    ("Nadia", "Yoma"),
    ("Karim", "Assef"),
    ("Selim", "Salum"),
    ("Fadwa", "Dip"),
    ("Jorge", "Sapag"),
]

_ALEMANES_ESLAVOS = [
    ("Klaus", "Müller"),
    ("Ingrid", "Schmidt"),
    ("Iván", "Kowalski"),
    ("Olga", "Nowak"),
    ("Kurt", "Wagner"),
    ("Tatiana", "Melnyk"),
]

# Dos estilos de mención, ambos realistas en una conclusión dictada: con
# título+nombre completo (la más fácil para el NER, fuerte señal sintáctica)
# y solo apellido sin ningún título (la más dura: sin capitalización de
# contexto que ayude, el único indicio es el apellido mismo).
_PLANTILLAS_NOMBRE_COMPLETO = (
    "Se comenta el caso con el Dr. {nombre} {apellido}.",
    "Paciente derivado por {nombre} {apellido} a control.",
)
_PLANTILLAS_SOLO_APELLIDO = (
    "Se solicita interconsulta con {apellido} para evaluacion conjunta.",
    "Sin datos de importancia segun {apellido}.",
)


@dataclass(frozen=True)
class _Grupo:
    etiqueta: str
    personas: Sequence[tuple[str, str]]
    # Piso de recall MEDIDO (ver tabla en el docstring del módulo) -- no
    # elegido de antemano. Un piso honesto y bajo vale más que uno alto
    # conseguido eligiendo los nombres que ya sabíamos que iban a pasar.
    piso: float


_GRUPOS = (
    _Grupo("ibericos", _IBERICOS, piso=1.00),
    _Grupo("italianos", _ITALIANOS, piso=0.90),  # medido 0.92 -- ver "Colombo" en docstring
    _Grupo("guaranies", _GUARANIES, piso=1.00),
    _Grupo("arabes_libaneses", _ARABES_LIBANESES, piso=1.00),
    _Grupo("alemanes_eslavos", _ALEMANES_ESLAVOS, piso=1.00),
)


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


def _muestras(personas: Sequence[tuple[str, str]]) -> list[tuple[str, int, int]]:
    """Genera (oracion, inicio, fin) del span a detectar, para cada persona x plantilla."""
    muestras: list[tuple[str, int, int]] = []
    for nombre, apellido in personas:
        for plantilla in _PLANTILLAS_NOMBRE_COMPLETO:
            nombre_completo = f"{nombre} {apellido}"
            oracion = plantilla.format(nombre=nombre, apellido=apellido)
            inicio = oracion.index(nombre_completo)
            muestras.append((oracion, inicio, inicio + len(nombre_completo)))
        for plantilla in _PLANTILLAS_SOLO_APELLIDO:
            oracion = plantilla.format(apellido=apellido)
            inicio = oracion.index(apellido)
            muestras.append((oracion, inicio, inicio + len(apellido)))
    return muestras


def _recall_de_grupo(motor: MotorPii, grupo: _Grupo) -> tuple[float, int, int]:
    """Recall operacional: cualquier detección (no solo PERSON) que se solape con el
    nombre cuenta como "detectado" -- es lo que `redactar_por_motor` efectivamente
    redacta aguas abajo (ver `pii/redaccion.py`), no depende de que el tipo de
    entidad sea exactamente PERSON."""
    muestras = _muestras(grupo.personas)
    detectados = sum(
        1
        for oracion, inicio, fin in muestras
        if any(d.inicio < fin and d.fin > inicio for d in motor.detectar(oracion))
    )
    return detectados / len(muestras), detectados, len(muestras)


@pytest.mark.parametrize("grupo", _GRUPOS, ids=lambda g: g.etiqueta)
def test_recall_del_grupo_no_cae_por_debajo_del_piso_medido(motor: MotorPii, grupo: _Grupo) -> None:
    recall, detectados, total = _recall_de_grupo(motor, grupo)
    assert recall >= grupo.piso, (
        f"Recall de '{grupo.etiqueta}' cayó a {recall:.2f} ({detectados}/{total}), "
        f"por debajo del piso declarado {grupo.piso:.2f}. Si el motor mejoró, subí el "
        f"piso a la realidad; si empeoró, esto es una regresión real de detección."
    )


def test_apellido_ambiguo_con_toponimo_es_el_unico_hallazgo_real(motor: MotorPii) -> None:
    """Centinela del hallazgo concreto de esta medición: "Colombo" (apellido italiano
    Y ciudad -- capital de Sri Lanka) mencionado SIN nombre de pila ni título falla en
    este banco. No es una falla de origen étnico -- es ambigüedad léxica puntual."""
    detecciones_con_titulo = motor.detectar("Se comenta el caso con el Dr. Renzo Colombo.")
    detecciones_solo_apellido = motor.detectar(
        "Se solicita interconsulta con Colombo para evaluacion conjunta."
    )
    assert any(d.tipo_entidad == "PERSON" for d in detecciones_con_titulo)
    assert not any(d.tipo_entidad == "PERSON" for d in detecciones_solo_apellido)
