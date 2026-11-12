"""Política de PII: clasifica cada hallazgo en su namespace (paciente/médico/cuasi-id) para
que `pseudonimizacion/claves.py` genere la clave HMAC correspondiente. Sin imports de `parseo` (duck typing)."""

from __future__ import annotations

from dataclasses import dataclass

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.pii.motor import DeteccionPii, MotorPii

NAMESPACE_PACIENTE = "id_paciente"
# PII de un profesional, no del paciente: namespace propio, nunca mezclado con el del paciente.
NAMESPACE_MEDICO = "id_medico"
NAMESPACE_CUASI_IDENTIFICADOR = "cuasi_identificador"

_CLAVES_ADICIONALES_MEDICO = ("medico_derivante", "medico_solicitante")


@dataclass(frozen=True)
class ElementoPii:
    """Un valor de PII ya clasificado en su namespace."""

    namespace: str
    valor: str


@dataclass(frozen=True)
class ResultadoPolitica:
    """Salida de `clasificar`: PII agrupada por namespace + hallazgos en texto libre."""

    elementos_paciente: tuple[ElementoPii, ...]
    elementos_medico: tuple[ElementoPii, ...]
    cuasi_identificadores: tuple[ElementoPii, ...]
    detecciones_texto_libre: tuple[DeteccionPii, ...]


def _elementos_paciente(documento: DocumentoParseado) -> tuple[ElementoPii, ...]:
    identidad = documento.identidad
    elementos: list[ElementoPii] = [
        ElementoPii(namespace=NAMESPACE_PACIENTE, valor=identidad.nombre.get_secret_value())
    ]
    if identidad.dni is not None:
        elementos.append(
            ElementoPii(namespace=NAMESPACE_PACIENTE, valor=identidad.dni.get_secret_value())
        )
    if identidad.fecha_nac is not None:
        elementos.append(
            ElementoPii(
                namespace=NAMESPACE_PACIENTE, valor=identidad.fecha_nac.get_secret_value()
            )
        )
    return tuple(elementos)


def _cuasi_identificadores(documento: DocumentoParseado, motor: MotorPii) -> tuple[ElementoPii, ...]:
    valores = tuple(id_interno.get_secret_value() for id_interno in documento.identidad.ids_internos)
    motor.evaluar_ids_internos(valores)  # valida/marca vía el motor (ver motor.py)
    return tuple(
        ElementoPii(namespace=NAMESPACE_CUASI_IDENTIFICADOR, valor=valor) for valor in valores
    )


def _elementos_medico(documento: DocumentoParseado) -> tuple[ElementoPii, ...]:
    elementos: list[ElementoPii] = []
    for clave in _CLAVES_ADICIONALES_MEDICO:
        valor = documento.adicionales.get(clave)
        if valor:
            elementos.append(ElementoPii(namespace=NAMESPACE_MEDICO, valor=str(valor)))

    firma = getattr(documento.contenido, "firma", None)
    nombre_firma = getattr(firma, "nombre", None) if firma is not None else None
    if nombre_firma:
        elementos.append(ElementoPii(namespace=NAMESPACE_MEDICO, valor=nombre_firma))

    return tuple(elementos)


def _detecciones_texto_libre(documento: DocumentoParseado, motor: MotorPii) -> tuple[DeteccionPii, ...]:
    secciones = getattr(documento.contenido, "secciones_texto", ())
    detecciones: list[DeteccionPii] = []
    for seccion in secciones:
        texto = getattr(seccion, "texto", "")
        if texto:
            detecciones.extend(motor.detectar(texto))
    return tuple(detecciones)


def clasificar(documento: DocumentoParseado, motor: MotorPii) -> ResultadoPolitica:
    """Clasifica la PII de un `DocumentoParseado` en sus namespaces (paciente/médico/cuasi-id)."""
    return ResultadoPolitica(
        elementos_paciente=_elementos_paciente(documento),
        elementos_medico=_elementos_medico(documento),
        cuasi_identificadores=_cuasi_identificadores(documento, motor),
        detecciones_texto_libre=_detecciones_texto_libre(documento, motor),
    )
