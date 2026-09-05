"""Los dos defectos de `escritura-idempotente`, cerrados de punta a punta.

El primero era duplicación: procesar el mismo documento N veces dejaba N filas.
El segundo era pérdida: publicar un episodio de tres documentos dejaba uno solo.

El camino de la duplicación se ejercita **por la raíz de composición de
producción** (`tareas.construir_fabrica_ejecutor`), no armando el ejecutor a
mano. Ésa es la lección de un bug anterior de este repo: un test que ensambla su
propio cableado valida algo que producción no usa.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import sqlalchemy as sa
from sqlalchemy.orm import Session

os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"

from anonimizacion.dominio.modelos import RegistroAnonimizado  # noqa: E402
from anonimizacion.dominio.tipos_documento import TipoDocumento  # noqa: E402
from anonimizacion.pii.motor import MotorPii  # noqa: E402
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves  # noqa: E402
from anonimizacion.salida.cuarentena import EscritorCuarentena  # noqa: E402
from anonimizacion.salida.destinos.parquet import EscritorParquet  # noqa: E402
from anonimizacion.salida.destinos.postgres import EscritorPostgres  # noqa: E402
from anonimizacion.salida.modelos_orm import Base, Estudio  # noqa: E402
from anonimizacion.salida.publicador_bundles import PublicadorBundles  # noqa: E402
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
            resultados = tareas.procesar_grupo(referencias)
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


def test_publicar_un_episodio_de_tres_documentos_los_conserva_a_los_tres() -> None:
    """Antes del arreglo sobrevivia uno solo: `escribir_episodio` sobrescribia."""
    base = Path(tempfile.mkdtemp())
    publicador = PublicadorBundles(base / "bundles", EscritorParquet(base / "parquet"))

    registros = [
        RegistroAnonimizado(
            id_paciente="pid-1",
            id_episodio="ep-1",
            tipo_documento=tipo,
            version_esquema=1,
            fecha_estudio=date(2024, 1, 10),
            contenido=None,
            clave_documento=clave,
        )
        for tipo, clave in (
            (TipoDocumento.ECG, "clave-sintetica-ecg"),
            (TipoDocumento.LABORATORIO, "clave-sintetica-lab"),
            (TipoDocumento.ECOCARDIOGRAMA, "clave-sintetica-eco"),
        )
    ]

    publicador.publicar(registros, version_pipeline="v1")

    filas = pq.read_table(base / "parquet" / "episodios" / "ep-1.parquet").to_pylist()
    assert len(filas) == 3
    assert sorted(fila["tipo_documento"] for fila in filas) == [
        "ecg",
        "ecocardiograma",
        "laboratorio",
    ]

    # Republicar no agrega ni pierde nada.
    publicador.publicar(registros, version_pipeline="v1")
    filas_tras_republicar = pq.read_table(
        base / "parquet" / "episodios" / "ep-1.parquet"
    ).to_pylist()
    assert len(filas_tras_republicar) == 3


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
