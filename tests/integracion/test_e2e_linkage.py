"""Test E2E (tasks.md 11.4, spec `pseudonymous-linkage`, "ECG+Lab+Eco del mismo paciente <=7 dias").

Ejercita `EjecutorPipeline.procesar_lote` de punta a punta -- extracción,
detección, parseo, `MotorPii` real, resolución de claves (`ResolutorClaves`,
el laboratorio como puente), `vinculacion.py` (clustering por ancla ±7
días), `construir_registro`, storage SQLite real -- con 3 documentos
sintéticos del MISMO paciente (mismo nombre+DNI+fecha de nacimiento
coherentes entre los 3) con fechas dentro de la ventana de 7 días, y
verifica que los 3 terminan con el MISMO `id_paciente` y el MISMO
`id_episodio`.

Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
recalibración parser ECG contra layout real Mortara"): la versión original
de este test (PR9) necesitaba un `_ParseadorEcgConFechaNacInyectada` de test
que envolvía al parser real e inyectaba `fecha_nac` a mano, porque
`parseo/ecg_mortara.py` dejaba ese campo SIEMPRE en `None` -- el formato
sintético original contra el que se había construido el parser no incluía
fecha de nacimiento. Tras recalibrar el parser contra el layout REAL del
equipo (que sí trae fecha de nacimiento, junto con edad y sexo, en la misma
línea que el estudio), el parser real la extrae solo -- este test ahora usa
`obtener_parseador` (el resolver REAL, sin fakes ni wrappers) para las tres
etapas, probando el puente `id_alt_paciente -> id_paciente` de punta a
punta tal como lo vería producción.

También ejercita que el `id_alt_paciente` se resuelve pese a que el
laboratorio (`DD/MM/YYYY`) y el ECG (`DD-MON-YYYY`) usan formatos de fecha
de nacimiento distintos: ambos parsers normalizan a ISO 8601 antes de
calcular el HMAC (ver `parseo/laboratorio_general.py` y
`parseo/ecg_mortara.py`, `_parsear_fecha_nacimiento`) -- sin esa
normalización, el mismo paciente real produciría dos `id_alt_paciente`
distintos y el puente nunca resolvería.
"""

from __future__ import annotations

import sqlalchemy as sa

from anonimizacion.ingesta.fuente import FuenteLocal
from anonimizacion.parseo.registro import obtener_parseador
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import ExitoDocumento
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Base

from ..fixtures.v1 import documentos

PEPPER = b"pepper-e2e-11-4-nunca-real"


def test_ecg_lab_eco_mismo_paciente_dentro_de_7_dias_terminan_con_mismo_paciente_y_episodio(
    tmp_path, motor: MotorPii
) -> None:
    nombre = "Lucia Sintetica Seis"
    dni = "31777888"
    # Misma fecha de nacimiento real, en el formato propio de cada equipo --
    # el laboratorio usa DD/MM/YYYY, el ECG usa DD-MON-YYYY (ver docstring).
    fecha_nac_lab = "03/03/1990"
    fecha_nac_ecg = "03-MAR-1990"

    artefacto_lab = documentos.escribir_pdf(
        tmp_path,
        "lab-e2e",
        documentos.texto_laboratorio(
            nombre=nombre, dni=dni, fecha_nac=fecha_nac_lab, numero_peticion="PET-E2E-1", fecha="10/01/2024"
        ),
    )
    artefacto_ecg = documentos.escribir_pdf(
        tmp_path,
        "ecg-e2e",
        documentos.texto_ecg(
            nombre=nombre,
            id_estudio="ECG-E2E-1",
            fecha="13-JAN-2024",
            fecha_nac=fecha_nac_ecg,
            edad_anios=33,
        ),
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
        fuente=FuenteLocal(raices=(tmp_path,), directorio=tmp_path),
        obtener_parseador=obtener_parseador,  # resolver REAL -- sin fakes/wrappers de test
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
    # si el ECG no hubiera resuelto el puente, habría terminado en
    # CLAVE_PII_NO_RESUELTA -> cuarentena, y no estaría en `exitos` -- esta
    # aserción es la que prueba que el puente REAL funciona, no solo el
    # algoritmo de vinculación con una identidad inyectada a mano.
    assert set(exitos) == {"doc-lab", "doc-ecg", "doc-eco"}

    ids_paciente = {r.id_paciente for r in exitos.values()}
    ids_episodio = {r.id_episodio for r in exitos.values()}

    assert len(ids_paciente) == 1  # mismo id_paciente para los 3 (fecha_estudio 10/13/16 enero, <=7 dias del ancla)
    assert len(ids_episodio) == 1  # mismo episodio: ninguno excede la ventana de +-7 dias del ancla (10/01)
