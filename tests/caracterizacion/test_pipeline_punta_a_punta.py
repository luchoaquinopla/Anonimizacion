"""Caracterización punta a punta del pipeline (Entrega 0, Requisito 1).

Fija, sobre Postgres real y efímero (`engine_caracterizacion`), las filas que
el sistema HOY escribe en `episodio`/`estudio`/`cuarentena` para un corpus
sintético con un episodio completo, uno incompleto, uno ambiguo y un
documento en cuarentena (layout no reconocido). Reusa `procesar_carpeta.py`
por ruta -- mismo patrón que `tests/scripts/test_procesar_carpeta.py` -- para
ejercitar el composition root real, no una llamada aislada a una etapa.

No caracteriza NADA del universo de un 4to tipo de documento (`design.md`,
D1): sólo los 3 `TipoDocumento` alcanzables hoy en `main`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.pii.motor import MotorPii
from anonimizacion.salida.modelos_orm import Cuarentena, Episodio, Estudio

from ..fixtures.v1 import documentos

pytestmark = [pytest.mark.caracterizacion, pytest.mark.postgres]

_RUTA_SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "procesar_carpeta.py"
PEPPER = b"pepper-caracterizacion-e0-nunca-real"


def _cargar_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_procesar_carpeta_caracterizacion", _RUTA_SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


def _episodio_completo(directorio: Path) -> None:
    documentos.escribir_pdf(
        directorio,
        "01-lab-completo",
        documentos.texto_laboratorio(
            nombre="Episodio Completo",
            dni="20111000",
            fecha_nac="03/03/1980",
            numero_peticion="PET-completo",
            fecha="10/01/2024",
        ),
    )
    documentos.escribir_pdf(
        directorio,
        "02-ecg-completo",
        documentos.texto_ecg(
            nombre="Episodio Completo",
            id_estudio="ECG-completo",
            fecha="11-JAN-2024",
            fecha_nac="03-MAR-1980",
            edad_anios=44,
            sexo="Male",
        ),
    )
    documentos.escribir_pdf(
        directorio,
        "03-eco-completo",
        documentos.texto_eco(
            nombre="Episodio Completo",
            dni="20111000",
            numero_estudio="ECO-completo",
            fecha="12/01/2024",
        ),
    )


def _episodio_incompleto(directorio: Path) -> None:
    # Sólo laboratorio: al cierre del grupo (unidad completa, `ejecutor.py`)
    # cae en cuarentena por `EPISODIO_INCOMPLETO`.
    documentos.escribir_pdf(
        directorio,
        "04-lab-incompleto",
        documentos.texto_laboratorio(
            nombre="Episodio Incompleto",
            dni="20222000",
            fecha_nac="04/04/1981",
            numero_peticion="PET-incompleto",
            fecha="10/01/2024",
        ),
    )


def _episodio_ambiguo(directorio: Path) -> None:
    # Dos laboratorios del mismo paciente en la misma ventana: dos documentos
    # del mismo `TipoDocumento` en un episodio => `EPISODIO_AMBIGUO`.
    documentos.escribir_pdf(
        directorio,
        "05-lab-ambiguo-a",
        documentos.texto_laboratorio(
            nombre="Episodio Ambiguo",
            dni="20333000",
            fecha_nac="05/05/1982",
            numero_peticion="PET-ambiguo-a",
            fecha="10/01/2024",
        ),
    )
    documentos.escribir_pdf(
        directorio,
        "06-lab-ambiguo-b",
        documentos.texto_laboratorio(
            nombre="Episodio Ambiguo",
            dni="20333000",
            fecha_nac="05/05/1982",
            numero_peticion="PET-ambiguo-b",
            fecha="11/01/2024",
        ),
    )


def _documento_en_cuarentena(directorio: Path) -> None:
    # Layout no reconocido: nunca entra a ningún episodio, va directo a
    # cuarentena por `TIPO_NO_RECONOCIDO`.
    documentos.escribir_pdf(directorio, "07-layout-no-reconocido", documentos.texto_layout_no_reconocido())


def test_corpus_sintetico_fija_las_filas_de_episodio_y_estudio(tmp_path: Path, motor: MotorPii, engine_caracterizacion: sa.Engine) -> None:
    """Escenario "episodio completo fija filas conocidas" + los otros tres desenlaces."""
    _episodio_completo(tmp_path)
    _episodio_incompleto(tmp_path)
    _episodio_ambiguo(tmp_path)
    _documento_en_cuarentena(tmp_path)

    modulo = _cargar_script()
    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine_caracterizacion, motor=motor, pepper=PEPPER)

    assert codigo == 0

    with Session(engine_caracterizacion) as sesion:
        episodios = sesion.scalars(sa.select(Episodio)).all()
        estudios = sesion.scalars(sa.select(Estudio)).all()
        cuarentenas = sesion.scalars(sa.select(Cuarentena)).all()

    # Episodio completo: exactamente un episodio con sus 3 estudios publicados.
    assert len(episodios) == 1, "el episodio completo debe fijar exactamente 1 fila en `episodio`"
    (episodio,) = episodios
    assert len(estudios) == 3, "los 3 documentos del episodio completo deben publicarse en `estudio`"
    assert all(estudio.corrida_id is not None for estudio in estudios)

    # Cuarentena: incompleto (1) + ambiguo (2) + layout no reconocido (1) = 4 filas.
    assert len(cuarentenas) == 4
    codigos = sorted(fila.codigo for fila in cuarentenas)
    assert codigos == sorted(
        [
            CodigoErrorDocumento.EPISODIO_INCOMPLETO.value,
            CodigoErrorDocumento.EPISODIO_AMBIGUO.value,
            CodigoErrorDocumento.EPISODIO_AMBIGUO.value,
            CodigoErrorDocumento.TIPO_NO_RECONOCIDO.value,
        ]
    )

    etapas_por_codigo = {fila.codigo: fila.etapa for fila in cuarentenas}
    assert etapas_por_codigo[CodigoErrorDocumento.EPISODIO_INCOMPLETO.value] == "coordinacion"
    assert etapas_por_codigo[CodigoErrorDocumento.EPISODIO_AMBIGUO.value] == "coordinacion"
    assert etapas_por_codigo[CodigoErrorDocumento.TIPO_NO_RECONOCIDO.value] == "parseo"
