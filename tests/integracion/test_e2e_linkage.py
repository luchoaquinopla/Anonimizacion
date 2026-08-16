"""Test E2E (tasks.md 11.4, spec `pseudonymous-linkage`, "ECG+Lab+Eco del mismo paciente <=7 dias").

Ejercita `EjecutorPipeline.procesar_lote` de punta a punta -- extracción,
detección, parseo, `MotorPii` real, resolución de claves (`ResolutorClaves`,
el laboratorio como puente), `vinculacion.py` (clustering por ancla ±7
días), `construir_registro`, storage SQLite real -- con 3 documentos
sintéticos del MISMO paciente (mismo nombre+DNI+fecha de nacimiento
coherentes entre los 3) con fechas dentro de la ventana de 7 días, y
verifica que los 3 terminan con el MISMO `id_paciente` y el MISMO
`id_episodio`.

**Gap descubierto durante este test, documentado acá y en el reporte final
de PR9** (no se resuelve en este PR -- ver más abajo): `parseo/ecg_mortara.py`
deja `IdentidadCruda.fecha_nac` SIEMPRE en `None` -- el header real de un
ECG (spec `document-parsing`) nunca trae fecha de nacimiento. Pero
`pseudonimizacion/resolutor_claves.py` (PR5, ver
`tests/pseudonimizacion/test_resolutor_claves.py`) asume que un ECG puede
resolver su `id_alt_paciente` vía nombre+fecha_nac para encontrar el puente
que dejó el laboratorio (design.md, decisión 1). Con el parser REAL tal
como está, un ECG real JAMÁS puede resolver esa clave: `resolver_claves`
recibe `fecha_nac=None` y termina en `CLAVE_PII_NO_RESUELTA` siempre, sin
excepción. Esto es una inconsistencia real entre design.md (decisión 1) y
el campo de header que el propio spec `document-parsing` define para ECG
(que no incluye fecha de nacimiento) -- no es un bug de parseo corregible
sin inventar un dato que el documento no trae; es una decisión de negocio/
arquitectura pendiente (ver reporte final de PR9).

Para poder ejercitar el ALGORITMO de linkage end-to-end (que sí es 100%
responsabilidad de Fase 11) sin inventar una fuente real de `fecha_nac` para
ECG, este test inyecta un `obtener_parseador` que delega al parser REAL de
ECG para todo (medidas, adicionales, tolerancia a advertencias) y solo
completa `identidad.fecha_nac` después, con el mismo valor sintético que el
laboratorio del mismo paciente ya trajo -- documentado explícitamente como
un workaround de test, no como una corrección de `ecg_mortara.py`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import sqlalchemy as sa
from pydantic import SecretStr

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.ecg_mortara import ParseadorEcgMortara
from anonimizacion.parseo.registro import obtener_parseador as _obtener_parseador_real
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base

from ..fixtures.v1 import documentos

PEPPER = b"pepper-e2e-11-4-nunca-real"


class _ParseadorEcgConFechaNacInyectada:
    """Envuelve `ParseadorEcgMortara` real; solo completa `fecha_nac` (ver docstring del módulo)."""

    tipo_documento = TipoDocumento.ECG

    def __init__(self, fecha_nac: str) -> None:
        self._real = ParseadorEcgMortara()
        self._fecha_nac = fecha_nac

    def parsear(self, texto):
        documento = self._real.parsear(texto)
        identidad_con_fecha_nac = documento.identidad.model_copy(
            update={"fecha_nac": SecretStr(self._fecha_nac)}
        )
        return dataclasses.replace(documento, identidad=identidad_con_fecha_nac)


def _obtener_parseador_hibrido(fecha_nac: str):
    def _resolver(tipo: TipoDocumento):
        if tipo is TipoDocumento.ECG:
            return _ParseadorEcgConFechaNacInyectada(fecha_nac)
        return _obtener_parseador_real(tipo)

    return _resolver


def test_ecg_lab_eco_mismo_paciente_dentro_de_7_dias_terminan_con_mismo_paciente_y_episodio(
    tmp_path, motor: MotorPii
) -> None:
    nombre = "Lucia Sintetica Seis"
    dni = "31777888"
    fecha_nac = "1990-03-03"

    artefacto_lab = documentos.escribir_pdf(
        tmp_path,
        "lab-e2e",
        documentos.texto_laboratorio(
            nombre=nombre, dni=dni, fecha_nac=fecha_nac, numero_peticion="PET-E2E-1", fecha="10/01/2024"
        ),
    )
    artefacto_ecg = documentos.escribir_pdf(
        tmp_path,
        "ecg-e2e",
        documentos.texto_ecg(nombre=nombre, id_estudio="ECG-E2E-1", fecha="13/01/2024"),
    )
    artefacto_eco = documentos.escribir_pdf(
        tmp_path,
        "eco-e2e",
        documentos.texto_eco(nombre=nombre, dni=dni, numero_estudio="EST-E2E-1", fecha="16/01/2024"),
    )

    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    ejecutor = EjecutorPipeline(
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
        obtener_parseador=_obtener_parseador_hibrido(fecha_nac),
    )

    # el laboratorio se procesa PRIMERO: registra el puente id_alt_paciente ->
    # id_paciente que el ECG necesita para resolver (ver resolutor_claves.py).
    items = [
        ItemLote(id_documento="doc-lab", artefacto=artefacto_lab),
        ItemLote(id_documento="doc-ecg", artefacto=artefacto_ecg),
        ItemLote(id_documento="doc-eco", artefacto=artefacto_eco),
    ]

    resultados = ejecutor.procesar_lote(items)

    exitos = {r.id_documento: r for r in resultados if isinstance(r, ExitoDocumento)}
    assert set(exitos) == {"doc-lab", "doc-ecg", "doc-eco"}

    ids_paciente = {r.id_paciente for r in exitos.values()}
    ids_episodio = {r.id_episodio for r in exitos.values()}

    assert len(ids_paciente) == 1  # mismo id_paciente para los 3 (fecha_estudio 10/13/16 enero, <=7 dias del ancla)
    assert len(ids_episodio) == 1  # mismo episodio: ninguno excede la ventana de +-7 dias del ancla (10/01)
