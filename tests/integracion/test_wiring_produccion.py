"""Test de integración (fase 7, openspec `puerto-de-ingesta`, tasks.md 7.3).

Confirma que `trabajadores/tareas.py::construir_fabrica_ejecutor` es la raíz
de composición real del worker: arma una `FuenteLocal` UNA sola vez y la
inyecta en `EjecutorPipeline(fuente=...)`, de modo que `procesar_documento`
(la tarea Celery real, con `CELERY_TASK_ALWAYS_EAGER`) resuelve un documento
de punta a punta sin que `tareas.py` conozca `pathlib` en ningún punto
propio -- toda la resolución de la `uri` pasa por el puerto de ingesta.
"""

from __future__ import annotations

import os

import sqlalchemy as sa

os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"

from anonimizacion.pii.motor import MotorPii  # noqa: E402
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves  # noqa: E402
from anonimizacion.salida.cuarentena import EscritorCuarentena  # noqa: E402
from anonimizacion.salida.destinos.postgres import EscritorPostgres  # noqa: E402
from anonimizacion.salida.modelos_orm import Base  # noqa: E402
from anonimizacion.trabajadores import tareas  # noqa: E402

from ..fixtures.v1 import documentos

PEPPER = b"pepper-wiring-produccion-nunca-real"


def _grupo_completo(directorio, sufijo: str):
    """Los tres estudios de un mismo paciente sintetico: un episodio completo.

    Un documento suelto ya NO es un lote valido: con la validacion de episodio
    activa en la fabrica de produccion, un lote de uno nunca tiene los tres tipos
    requeridos y va entero a cuarentena. Esa es la conducta buscada.
    """
    return [
        documentos.escribir_pdf(
            directorio,
            f"lab-{sufijo}",
            documentos.texto_laboratorio(
                nombre="Ana Sintetica Grupo",
                dni="20555888",
                fecha_nac="05/05/1992",
                numero_peticion=f"PET-{sufijo}",
                fecha="10/01/2024",
            ),
        ),
        documentos.escribir_pdf(
            directorio,
            f"ecg-{sufijo}",
            documentos.texto_ecg(
                nombre="Ana Sintetica Grupo",
                id_estudio=f"ECG-{sufijo}",
                fecha="11-JAN-2024",
                fecha_nac="05-MAY-1992",
                edad_anios=31,
                sexo="Female",
            ),
        ),
        documentos.escribir_pdf(
            directorio,
            f"eco-{sufijo}",
            documentos.texto_eco(
                nombre="Ana Sintetica Grupo",
                dni="20555888",
                numero_estudio=f"ECO-{sufijo}",
                fecha="12/01/2024",
            ),
        ),
    ]


def _referencias(artefactos):
    return [
        {"id_documento": f"doc-{indice}", "uri": a.uri, "sha256": a.sha256}
        for indice, a in enumerate(artefactos)
    ]



def test_construir_fabrica_ejecutor_procesa_un_grupo_real_de_punta_a_punta(
    tmp_path, motor: MotorPii
) -> None:
    artefactos = _grupo_completo(tmp_path, "wiring")

    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    destino = EscritorPostgres(engine)
    cuarentena = EscritorCuarentena(engine)

    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(tmp_path,),
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=destino,
        cuarentena=cuarentena,
    )
    tareas.configurar_ejecutor(fabrica)
    try:
        # Las `uri` viajan como lo haria un mensaje real de cola -- si
        # `construir_fabrica_ejecutor` no hubiera armado la `FuenteLocal` con
        # `tmp_path` como raiz autorizada, esto fallaria con `PermissionError`.
        resultados = tareas.procesar_grupo(_referencias(artefactos))
    finally:
        tareas._fabrica_ejecutor = None

    assert len(resultados) == 3
    assert {resultado["estado"] for resultado in resultados} == {"exito"}


def test_un_documento_suelto_por_la_fabrica_real_va_a_cuarentena(
    tmp_path, motor: MotorPii
) -> None:
    """La fabrica de produccion valida episodios: un documento solo no es uno.

    Antes de este cambio este mismo caso devolvia `exito`, porque la validacion
    de episodio no corria en produccion.
    """
    artefactos = _grupo_completo(tmp_path, "suelto")

    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(tmp_path,),
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
    )
    tareas.configurar_ejecutor(fabrica)
    try:
        (resultado,) = tareas.procesar_grupo(_referencias(artefactos[:1]))
    finally:
        tareas._fabrica_ejecutor = None

    assert resultado["estado"] != "exito"
    assert resultado["codigo"] == "episodio_incompleto"
