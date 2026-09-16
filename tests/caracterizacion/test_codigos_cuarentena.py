"""Caracterización de códigos de cuarentena observables (Entrega 0, Requisito 3).

Fija, para un conjunto conocido de entradas inválidas, el par
`(CodigoErrorDocumento, etapa)` que hoy produce cada una -- sin afirmar nada
sobre qué clase lo lanzó (`design.md`, tabla "caracterizar la superficie").
Reusa `anonimizacion.comandos.procesar::ejecutar()` con SQLite en memoria
(mismo patrón que `tests/comandos/test_procesar.py`): no necesita Postgres
real, a diferencia de `test_pipeline_punta_a_punta.py`.

Corrección mecánica (auditoria-y-poda, E4): `ejecutar()` vivía en
`scripts/procesar_carpeta.py`, cargado por ruta porque `scripts/` no era un
paquete instalado; E4 lo movió a `anonimizacion.comandos.procesar` (paquete
real). Este archivo no afirma nada sobre CÓMO se carga el módulo -- sólo lo
usa como fixture para llegar a `ejecutar()` -- así que sólo cambia el
`import`, ninguna aserción de las de abajo.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.pii.motor import MotorPii
from anonimizacion.salida.modelos_orm import Base, Cuarentena

from ..fixtures.v1 import documentos

pytestmark = pytest.mark.caracterizacion

PEPPER = b"pepper-caracterizacion-cuarentena-nunca-real"


def _cargar_script() -> ModuleType:
    """Import normal -- ver nota de corrección mecánica arriba."""
    from anonimizacion.comandos import procesar as modulo

    return modulo


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


def _procesar(tmp_path: Path, motor: MotorPii) -> tuple[Cuarentena, ...]:
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    modulo = _cargar_script()
    modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)
    with Session(engine) as sesion:
        return tuple(sesion.scalars(sa.select(Cuarentena)).all())


def test_layout_no_reconocido_produce_tipo_no_reconocido_en_parseo(tmp_path: Path, motor: MotorPii) -> None:
    documentos.escribir_pdf(tmp_path, "roto", documentos.texto_layout_no_reconocido())

    (fila,) = _procesar(tmp_path, motor)

    assert fila.codigo == "tipo_no_reconocido"
    assert fila.etapa == "parseo"


def test_pdf_corrupto_produce_pdf_ilegible_en_extraccion(tmp_path: Path, motor: MotorPii) -> None:
    (tmp_path / "corrupto.pdf").write_bytes(b"esto no es un PDF valido")

    (fila,) = _procesar(tmp_path, motor)

    assert fila.codigo == "pdf_ilegible"
    assert fila.etapa == "extraccion"


def test_episodio_con_un_solo_tipo_produce_episodio_incompleto_en_coordinacion(
    tmp_path: Path, motor: MotorPii
) -> None:
    documentos.escribir_pdf(
        tmp_path,
        "lab-solo",
        documentos.texto_laboratorio(
            nombre="Solo Laboratorio",
            dni="20444000",
            fecha_nac="06/06/1983",
            numero_peticion="PET-solo",
            fecha="10/01/2024",
        ),
    )

    (fila,) = _procesar(tmp_path, motor)

    assert fila.codigo == "episodio_incompleto"
    assert fila.etapa == "coordinacion"


def test_dos_documentos_del_mismo_tipo_en_un_episodio_producen_episodio_ambiguo_en_coordinacion(
    tmp_path: Path, motor: MotorPii
) -> None:
    for sufijo in ("a", "b"):
        documentos.escribir_pdf(
            tmp_path,
            f"lab-dup-{sufijo}",
            documentos.texto_laboratorio(
                nombre="Duplicado Laboratorio",
                dni="20555000",
                fecha_nac="07/07/1984",
                numero_peticion=f"PET-dup-{sufijo}",
                fecha="10/01/2024",
            ),
        )

    filas = _procesar(tmp_path, motor)

    assert len(filas) == 2
    assert all(fila.codigo == "episodio_ambiguo" for fila in filas)
    assert all(fila.etapa == "coordinacion" for fila in filas)
