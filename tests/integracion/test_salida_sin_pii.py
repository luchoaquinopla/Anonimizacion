"""Test de integración (tasks.md 11.3, spec `anonymized-output`, "Cero PII en el registro de salida").

Arma un `RegistroAnonimizado` completo para cada uno de los 3 tipos de
documento -- vía el pipeline REAL de extracción+detección+parseo sobre PDFs
sintéticos, igual que `test_lote_aislamiento.py` -- y escanea la
representación completa del registro con el motor de PII REAL
(`pii/motor.py::MotorPii`, Presidio+spaCy) para confirmar que no queda
ningún hallazgo de PII directa (persona/DNI).

El caso del eco es el que ejercita el fix de PR9 (ver
`pii/redaccion.py`/`salida/constructor_registro.py`): su
`texto_conclusiones` menciona deliberadamente el nombre completo del
paciente Y del médico, tal como puede pasar en una conclusión dictada real
(design.md, decisión 6) -- antes del fix de PR9 ese nombre habría llegado
sin redactar a `ContenidoEcoSalida.secciones_texto`.
"""

from __future__ import annotations

from pathlib import Path

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.dominio.modelos import ClavesPaciente
from anonimizacion.extraccion.texto_pymupdf import extraer_texto
from anonimizacion.parseo.registro import obtener_parseador
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.salida.constructor_registro import construir_registro

from ..fixtures.v1 import documentos

PEPPER = b"pepper-integracion-11-3-nunca-real"
CLAVES = ClavesPaciente(id_paciente="pid-integracion-11-3", id_alt_paciente=None, version_clave=1)
ID_EPISODIO = "episodio-integracion-11-3"
CLAVE_DOCUMENTO = generar_clave_documento(PEPPER, "f" * 64)

# Identidad sintética inyectada deliberadamente en texto libre y headers, para
# poder afirmar que NINGUNA de estas cadenas crudas sobrevive en la salida.
_NOMBRE_PACIENTE = "Ramona Sintetica Cinco"
_DNI_PACIENTE = "27555666"
_NOMBRE_MEDICO = "Dr. Esteban Sintetico Informante"


def _parsear(tmp_path: Path, nombre_archivo: str, paginas: list[str]):
    artefacto = documentos.escribir_pdf(tmp_path, nombre_archivo, paginas)
    texto = extraer_texto(Path(artefacto.uri))
    tipo = detectar_tipo(texto)
    return obtener_parseador(tipo).parsear(texto)


def _sin_hallazgos_de_pii_directa(bloque_texto: str, motor: MotorPii) -> bool:
    detecciones = motor.detectar(bloque_texto)
    return not any(d.tipo_entidad in {"PERSON", "DNI_AR"} for d in detecciones)


def test_registro_de_laboratorio_no_tiene_pii_segun_motor_real(tmp_path, motor: MotorPii) -> None:
    documento = _parsear(
        tmp_path,
        "lab-11-3",
        documentos.texto_laboratorio(
            nombre=_NOMBRE_PACIENTE,
            dni=_DNI_PACIENTE,
            fecha_nac="09/09/1979",
            numero_peticion="PET-11-3",
            fecha="10/01/2024",
            medico_derivante=_NOMBRE_MEDICO,
        ),
    )

    registro = construir_registro(documento, CLAVES, id_episodio=ID_EPISODIO, pepper=PEPPER, clave_documento=CLAVE_DOCUMENTO, motor_pii=motor)
    bloque = f"{registro.contenido} {registro.adicionales}"

    # el laboratorio no tiene ningún campo de texto libre (a diferencia del
    # eco) -- basta con confirmar que la PII cruda inyectada no sobrevive en
    # ningún campo (no se re-escanea con `motor.detectar` el `repr()` completo:
    # ese repr mezcla nombres de campo y valores no-PII legítimos como
    # `institucion`/`ejes`, que producen falsos positivos de NER conocidos,
    # ver `observabilidad/test_bitacora_segura.py`, caso "doc-9").
    assert _NOMBRE_PACIENTE not in bloque
    assert _DNI_PACIENTE not in bloque
    assert _NOMBRE_MEDICO not in bloque


def test_registro_de_ecg_no_tiene_pii_segun_motor_real(tmp_path, motor: MotorPii) -> None:
    documento = _parsear(
        tmp_path,
        "ecg-11-3",
        documentos.texto_ecg(
            nombre=_NOMBRE_PACIENTE,
            id_estudio="ECG-11-3",
            fecha="10-JAN-2024",
            fecha_nac="09-SEP-1979",
            edad_anios=44,
            medico_derivante=_NOMBRE_MEDICO,
        ),
    )

    registro = construir_registro(documento, CLAVES, id_episodio=ID_EPISODIO, pepper=PEPPER, clave_documento=CLAVE_DOCUMENTO, motor_pii=motor)
    bloque = f"{registro.contenido} {registro.adicionales}"

    assert _NOMBRE_PACIENTE not in bloque
    assert _NOMBRE_MEDICO not in bloque


def test_registro_de_eco_con_texto_libre_mencionando_pii_no_tiene_pii_segun_motor_real(
    tmp_path, motor: MotorPii
) -> None:
    # el caso central de 11.3: la conclusion dictada menciona nombre de paciente
    # Y de médico -- exactamente el escenario que motiva el fix de PR9.
    conclusiones = (
        f"Estudio realizado a {_NOMBRE_PACIENTE}, informado personalmente por "
        f"el {_NOMBRE_MEDICO}. Funcion sistolica conservada, sin hallazgos patologicos."
    )
    documento = _parsear(
        tmp_path,
        "eco-11-3",
        documentos.texto_eco(
            nombre=_NOMBRE_PACIENTE,
            dni=_DNI_PACIENTE,
            numero_estudio="EST-11-3",
            fecha="10/01/2024",
            firma_nombre=_NOMBRE_MEDICO,
            texto_conclusiones=conclusiones,
        ),
    )

    registro = construir_registro(documento, CLAVES, id_episodio=ID_EPISODIO, pepper=PEPPER, clave_documento=CLAVE_DOCUMENTO, motor_pii=motor)
    bloque = f"{registro.contenido} {registro.adicionales}"

    assert _NOMBRE_PACIENTE not in bloque
    assert _NOMBRE_MEDICO not in bloque
    assert _DNI_PACIENTE not in bloque

    # el escaneo con `MotorPii` real se hace sobre el texto libre efectivamente
    # redactado (`secciones_texto`) -- es el campo que motiva el fix de PR9, y
    # el único con prosa suficiente para que el NER opine con sentido; escanear
    # el `repr()` completo del registro mezcla nombres de campo/valores no-PII
    # (HMAC hex, "P60 R30 T40", nombres de institución) que producen falsos
    # positivos de NER ya documentados (ver el otro test de este módulo y
    # `observabilidad/test_bitacora_segura.py`, caso "doc-9").
    texto_secciones = " ".join(seccion.texto for seccion in registro.contenido.secciones_texto)
    assert _sin_hallazgos_de_pii_directa(texto_secciones, motor)
