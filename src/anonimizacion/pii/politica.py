"""Política de PII: clasifica cada elemento en su namespace (spec `pii-detection`).

`pii/motor.py` sabe DETECTAR PII; este módulo decide QUÉ HACER con cada
hallazgo, clasificándolo en el namespace que va a usar Fase 6
(`pseudonimizacion/claves.py`) para generar la clave HMAC correspondiente:

- `NAMESPACE_PACIENTE` (`id_paciente`): nombre, DNI, fecha de nacimiento del
  paciente -- la identidad que el pipeline pseudonimiza como sujeto del
  estudio.
- `NAMESPACE_MEDICO` (`id_medico`): el médico derivante/solicitante/
  informante es PII de un profesional, NO del paciente (ver design.md,
  decisión Q3) -- namespace separado y propio, nunca mezclado con el del
  paciente ni vinculado al mismo grafo de identidad. Se recolecta tanto de
  `adicionales` (campos de header ya extraídos por los parsers, p.ej.
  `medico_derivante`/`medico_solicitante`) como de la firma al pie del
  informe (p.ej. `ContenidoEco.firma.nombre`), leída por duck typing.
- `NAMESPACE_CUASI_IDENTIFICADOR`: los IDs internos (Nº Petición, Nº
  Estudio, ID interno de ECG) vía `MotorPii.evaluar_ids_internos` -- no
  identifican por sí solos pero sí combinados con otros datos.
- Texto libre (p.ej. `ContenidoEco.secciones_texto`): se escanea con
  `MotorPii.detectar` porque puede traer PII no estructurada (un nombre
  mencionado en la conclusión dictada). No se le asigna namespace acá: la
  política solo señala el hallazgo con su posición en el texto: a qué
  persona pertenece (paciente, médico u otra) es una decisión de Fase 6/7
  que puede requerir contexto adicional (p.ej. comparar contra el nombre ya
  conocido del paciente/médico de ese mismo documento).

Duck typing, no imports de `anonimizacion.parseo`: esta fase (PR4) depende
solo de PR1 (dominio) según el Work Units table de `tasks.md`, y `parseo`
(PR3) es una fase paralela, no una dependencia.
"""

from __future__ import annotations

from dataclasses import dataclass

from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.pii.motor import DeteccionPii, MotorPii

NAMESPACE_PACIENTE = "id_paciente"
NAMESPACE_MEDICO = "id_medico"
NAMESPACE_CUASI_IDENTIFICADOR = "cuasi_identificador"

# Campos de header que los parsers ya dejan en `adicionales` con el nombre
# del médico derivante/solicitante (ver parseo/laboratorio_general.py y
# parseo/ecg_mortara.py: "medico_derivante"; parseo/eco_doppler.py:
# "medico_solicitante").
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
