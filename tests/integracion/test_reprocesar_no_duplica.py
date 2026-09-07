"""El defecto de duplicación de `escritura-idempotente`, cerrado de punta a punta.

Procesar el mismo documento N veces dejaba N filas. El camino se ejercita **por
la raíz de composición de producción** (`tareas.construir_fabrica_ejecutor`),
no armando el ejecutor a mano. Ésa es la lección de un bug anterior de este
repo: un test que ensambla su propio cableado valida algo que producción no
usa.

Nota (`chore/resolver-codigo-desconectado`): este archivo tenía un cuarto test
sobre `PublicadorBundles`/`EscritorParquet` (la pérdida de documentos al
publicar un episodio). Se eliminó junto con esos módulos: no tenían llamador
de producción -- ver `docs/pipeline.md`.
"""
from __future__ import annotations

import os
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"

from anonimizacion.dominio.modelos import RegistroAnonimizado  # noqa: E402
from anonimizacion.dominio.tipos_documento import TipoDocumento  # noqa: E402
from anonimizacion.pii.motor import MotorPii  # noqa: E402
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves  # noqa: E402
from anonimizacion.salida.cuarentena import EscritorCuarentena  # noqa: E402
from anonimizacion.salida.destinos.postgres import EscritorPostgres  # noqa: E402
from anonimizacion.salida.modelos_orm import Base, Cuarentena, Estudio  # noqa: E402
from anonimizacion.trabajadores import tareas  # noqa: E402

from ..fixtures.v1 import documentos  # noqa: E402

PEPPER = b"pepper-idempotencia-nunca-real"


def test_procesar_el_mismo_grupo_tres_veces_por_la_fabrica_real_no_duplica(
    tmp_path, motor: MotorPii
) -> None:
    artefactos = [
        documentos.escribir_pdf(
            tmp_path,
            "lab-idem",
            documentos.texto_laboratorio(
                nombre="Ana Sintetica Idem",
                dni="20555777",
                fecha_nac="04/04/1991",
                numero_peticion="PET-IDEM-1",
                fecha="10/01/2024",
            ),
        ),
        documentos.escribir_pdf(
            tmp_path,
            "ecg-idem",
            documentos.texto_ecg(
                nombre="Ana Sintetica Idem",
                id_estudio="ECG-IDEM",
                fecha="11-JAN-2024",
                fecha_nac="04-APR-1991",
                edad_anios=32,
                sexo="Female",
            ),
        ),
        documentos.escribir_pdf(
            tmp_path,
            "eco-idem",
            documentos.texto_eco(
                nombre="Ana Sintetica Idem",
                dni="20555777",
                numero_estudio="ECO-IDEM",
                fecha="12/01/2024",
            ),
        ),
    ]
    referencias = [
        {"id_documento": f"doc-idem-{indice}", "uri": a.uri, "sha256": a.sha256}
        for indice, a in enumerate(artefactos)
    ]

    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    destino = EscritorPostgres(engine)

    fabrica = tareas.construir_fabrica_ejecutor(
        raices=(tmp_path,),
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=destino,
        cuarentena=EscritorCuarentena(engine),
    )
    tareas.configurar_ejecutor(fabrica)
    try:
        # El mismo mensaje de grupo, tres veces: es lo que ocurre cuando una
        # corrida se corta y se relanza sobre el mismo corpus.
        for _ in range(3):
            resultados = tareas.procesar_grupo("corrida-idem", referencias)
            assert {resultado["estado"] for resultado in resultados} == {"exito"}
    finally:
        tareas._fabrica_ejecutor = None

    with Session(engine) as sesion:
        estudios = sesion.scalars(sa.select(Estudio)).all()

    assert len(estudios) == 3, "reprocesar el mismo grupo no debe crear filas nuevas"
    assert all(estudio.clave_documento is not None for estudio in estudios), (
        "sin clave de documento no hay garantia de idempotencia: la fabrica de "
        "produccion tiene que estar propagandola"
    )


def test_reprocesar_el_mismo_grupo_no_duplica_la_cuarentena(tmp_path, motor: MotorPii) -> None:
    """6.10: extiende el criterio de `escritura-idempotente` a cuarentena --
    reprocesar bajo la MISMA corrida no duplica el apartado (spec
    `trazabilidad-por-corrida`, Decisión 4: `UNIQUE(corrida_id, id_documento)`).

    Un documento solo (sin los otros dos tipos requeridos) va siempre a
    cuarentena por `episodio_incompleto` -- mismo camino que
    `test_wiring_produccion.py::test_un_documento_suelto_por_la_fabrica_real_va_a_cuarentena`,
    reprocesado tres veces con el mismo `corrida_id`.
    """
    artefacto = documentos.escribir_pdf(
        tmp_path,
        "lab-idem-cuarentena",
        documentos.texto_laboratorio(
            nombre="Ana Sintetica IdemQ",
            dni="20555778",
            fecha_nac="04/04/1991",
            numero_peticion="PET-IDEM-Q1",
            fecha="10/01/2024",
        ),
    )
    referencias = [{"id_documento": "doc-idem-q-0", "uri": artefacto.uri, "sha256": artefacto.sha256}]

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
        for _ in range(3):
            (resultado,) = tareas.procesar_grupo("corrida-idem-cuarentena", referencias)
            assert resultado["codigo"] == "episodio_incompleto"
    finally:
        tareas._fabrica_ejecutor = None

    with Session(engine) as sesion:
        filas = sesion.scalars(sa.select(Cuarentena)).all()

    assert len(filas) == 1, "reprocesar la misma corrida no debe duplicar el apartado"
    assert filas[0].corrida_id == "corrida-idem-cuarentena"


def test_un_documento_corregido_entra_como_documento_nuevo() -> None:
    """Ítem diferido desde el PR anterior: no se podia probar sin la restriccion unica.

    Contenido distinto produce clave distinta, luego es otro documento. El sistema
    no intenta decidir cual version es la vigente: no tiene informacion para
    hacerlo, y la fila anterior se conserva.
    """
    from anonimizacion.dominio.modelos import (
        ClavesPaciente,
        DocumentoParseado,
        IdentidadCruda,
    )
    from anonimizacion.parseo.ecg_mortara import ContenidoEcg
    from anonimizacion.pseudonimizacion.claves import generar_clave_documento
    from anonimizacion.salida.constructor_registro import construir_registro
    from pydantic import SecretStr

    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    escritor = EscritorPostgres(engine)
    escritor.escribir_episodio(
        id_episodio="ep-1", id_paciente="pid-1", fecha_ancla=date(2024, 1, 10)
    )

    def _registro(sha256: str) -> RegistroAnonimizado:
        documento = DocumentoParseado(
            tipo_documento=TipoDocumento.ECG,
            version_esquema=1,
            identidad=IdentidadCruda(nombre=SecretStr("Nombre Sintetico")),
            fecha_estudio=date(2024, 1, 10),
            contenido=ContenidoEcg(
                vent_rate="73",
                pr_interval="186",
                qrs_duration="100",
                qt_qtc="382/420",
                ejes="63 51 26",
            ),
        )
        return construir_registro(
            documento,
            ClavesPaciente(id_paciente="pid-1", id_alt_paciente=None, version_clave=1),
            id_episodio="ep-1",
            pepper=PEPPER,
            clave_documento=generar_clave_documento(PEPPER, sha256),
        )

    escritor.escribir_registro(_registro("a" * 64))
    escritor.escribir_registro(_registro("b" * 64))  # el documento se corrigio en el origen

    with Session(engine) as sesion:
        claves = sesion.scalars(sa.select(Estudio.clave_documento)).all()

    assert len(claves) == 2, "la version anterior se conserva; la corregida se agrega"
    assert len(set(claves)) == 2, "contenido distinto debe producir claves distintas"
