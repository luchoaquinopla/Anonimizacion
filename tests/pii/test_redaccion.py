"""Tests de `pii/redaccion.py`: filtro de redacción compartido (regex DNI + motor NER +
comparación exacta contra nombres ya conocidos del documento, Tarea 2).

`redactar_por_nombres_conocidos` es la red de contención que NO depende del NER: el
nombre del paciente y el del médico de ESE MISMO documento ya se conocen (vienen del
header parseado, `IdentidadCruda`/`adicionales`/`FirmaMedico`), así que cualquier
aparición literal de esos nombres -o de sus componentes- en el texto libre se redacta
por comparación exacta, sin depender de que spaCy/Presidio los reconozca como entidad.

Antes de esta Tarea, `pii/politica.py` (líneas 24-26) documentaba esto como una
intención futura ("una decisión de Fase 6/7 que puede requerir contexto adicional, p.ej.
comparar contra el nombre ya conocido del paciente/médico") -- pero rastreando el código
real de Fase 6/7 (`salida/constructor_registro.py`, `pii/redaccion.py`) esa comparación
NUNCA estaba implementada: `redactar_texto` solo aplicaba regex de DNI + `motor.detectar`
(NER), nunca comparaba contra el nombre conocido. Este archivo prueba la implementación
real que cierra ese hueco.
"""

from __future__ import annotations

from anonimizacion.pii.redaccion import (
    MARCADOR_REDACTADO,
    redactar_por_nombres_conocidos,
    redactar_texto,
)


def test_redacta_nombre_completo_conocido() -> None:
    texto = "Se comenta el caso con el Dr. Roberto Fernandez."
    redactado = redactar_por_nombres_conocidos(texto, ["Roberto Fernandez"])
    assert "Roberto Fernandez" not in redactado
    assert MARCADOR_REDACTADO in redactado


def test_redacta_componentes_del_nombre_por_separado() -> None:
    # El médico puede aparecer solo por su apellido, o solo con el nombre de pila,
    # sin el nombre completo tal cual figura en el header.
    texto = "Paciente derivado por el Dr. Fernandez a control."
    redactado = redactar_por_nombres_conocidos(texto, ["Roberto Fernandez"])
    assert "Fernandez" not in redactado


def test_no_redacta_tokens_de_conexion_cortos() -> None:
    # Nombres compuestos con conectores ("de", "la", "y") no deben convertir esas
    # palabras comunes en gatillos de redacción -- ver `_TOKEN_MINIMO`.
    texto = "El paciente vive en la casa de campo y no presenta sintomas."
    redactado = redactar_por_nombres_conocidos(texto, ["Ana de la Torre"])
    assert redactado == texto


def test_es_insensible_a_mayusculas_y_minusculas() -> None:
    texto = "el paciente fue visto por roberto fernandez la semana pasada."
    redactado = redactar_por_nombres_conocidos(texto, ["Roberto Fernandez"])
    assert "roberto fernandez" not in redactado.lower()


def test_texto_sin_coincidencias_queda_intacto() -> None:
    texto = "Funcion sistolica conservada, sin hallazgos patologicos."
    redactado = redactar_por_nombres_conocidos(texto, ["Roberto Fernandez"])
    assert redactado == texto


def test_lista_de_nombres_vacia_no_rompe() -> None:
    texto = "Funcion sistolica conservada."
    assert redactar_por_nombres_conocidos(texto, []) == texto


def test_redactar_texto_aplica_tambien_nombres_conocidos_sin_motor() -> None:
    # Integrado en `redactar_texto`: debe funcionar incluso en modo degradado
    # (sin `motor_pii` inyectado), igual que el regex de DNI.
    texto = "Se sugiere control con Dra. Ana Lopez en dos semanas."
    redactado = redactar_texto(texto, nombres_conocidos=["Ana Lopez"])
    assert "Ana Lopez" not in redactado


def test_redacta_nombre_conocido_con_acento_aunque_el_texto_no_lo_tenga() -> None:
    # Hallazgo de auditoría (fuga de PII por acentos): el header trae el
    # nombre con tilde tal cual lo escribe el sistema del instituto, pero el
    # dictado del informe frecuentemente omite los acentos. `IGNORECASE` no
    # cubre diacríticos -- sin el fix, "Maria Gonzalez" (sin tilde) sobrevive
    # intacto en el texto pese a que el nombre conocido es "María González".
    # Nombres sintéticos, no de un paciente real.
    texto = "Se comenta con Maria Gonzalez y su hijo sobre la evolucion."
    redactado = redactar_por_nombres_conocidos(texto, ["María González"])
    assert "Maria Gonzalez" not in redactado
    assert MARCADOR_REDACTADO in redactado


def test_redacta_nombre_conocido_sin_acento_aunque_el_texto_lo_tenga() -> None:
    # Dirección inversa: header sin tilde, texto libre con tilde.
    texto = "Se comenta con María González y su hijo sobre la evolucion."
    redactado = redactar_por_nombres_conocidos(texto, ["Maria Gonzalez"])
    assert "María González" not in redactado
    assert MARCADOR_REDACTADO in redactado


def test_nombre_conocido_de_una_letra_no_redacta_esa_letra_suelta() -> None:
    # Hallazgo de auditoría (sobre-redacción): el piso `_TOKEN_MINIMO` debe
    # aplicarse también al nombre completo, no sólo a sus tokens. Una
    # captura de header degenerada de una letra no puede convertirse en un
    # patrón que matchee cualquier "A" del texto libre.
    texto = "El paciente tiene un antecedente de asma leve."
    redactado = redactar_por_nombres_conocidos(texto, ["A"])
    assert redactado == texto


def test_nombres_conocidos_todos_degenerados_no_arma_patron_vacio() -> None:
    # Si tras el filtro de `_TOKEN_MINIMO` no queda ningún componente
    # utilizable (todos los nombres conocidos son demasiado cortos), no debe
    # armarse un patrón vacío que matchee cualquier posición del texto.
    texto = "Sin hallazgos patologicos en el estudio."
    redactado = redactar_por_nombres_conocidos(texto, ["A", "B", ""])
    assert redactado == texto
