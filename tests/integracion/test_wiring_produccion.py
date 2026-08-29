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


def test_construir_fabrica_ejecutor_procesa_documento_real_de_punta_a_punta(
    tmp_path, motor: MotorPii
) -> None:
    artefacto = documentos.escribir_pdf(
        tmp_path,
        "lab-wiring",
        documentos.texto_laboratorio(
            nombre="Ana Sintetica Wiring",
            dni="20555666",
            fecha_nac="03/03/1990",
            numero_peticion="PET-WIRE-1",
            fecha="10/01/2024",
        ),
    )

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
        # la `uri` viaja tal como lo haria un mensaje real de cola -- si
        # `construir_fabrica_ejecutor` no hubiera armado la `FuenteLocal` con
        # `tmp_path` como raiz autorizada, esto fallaria con `PermissionError`.
        resultado = tareas.procesar_documento("doc-wiring", artefacto.uri, artefacto.sha256)
    finally:
        tareas._fabrica_ejecutor = None

    assert resultado["estado"] == "exito"
