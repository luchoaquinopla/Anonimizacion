"""Tests de `scripts/procesar_carpeta.py` (tasks.md 6.8-6.9, PR 2.5).

Confirma que el script ya no arma `FuenteLocal`/`ItemLote` a mano ni llama
`ejecutor.procesar_lote(items)` sin corrida: usa `LanzadorCorrida` para
inventariar y `trabajadores.tareas.procesar_grupo` -- la misma tarea Celery
real que despachara producción (design.md, "Recorrido":
`LanzadorCorrida.lanzar` -> `procesar_grupo(corrida_id, referencias)` ->
`procesar_lote(items, corrida_id=...)`) -- para procesar. Sin este cambio
`LanzadorCorrida`/`CuarentenaDeCorrida` (Fase 6.4-6.7, ya mergeadas) no
tienen ningún llamador de producción.

También demuestra de punta a punta, desde el script, el caso que justifica
`CuarentenaDeCorrida` en vez de estado de corrida en `FuenteLocal`: un
artefacto apartado por sobretamaño -- ANTES de que se calcule su huella, así
que nunca puede inventariarse -- igual queda atribuido a su corrida.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.pii.motor import MotorPii
from anonimizacion.salida.modelos_orm import Base, CorridaOrm, Cuarentena, Estudio
from anonimizacion.trabajadores import tareas

from ..fixtures.v1 import documentos

_RUTA_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "procesar_carpeta.py"

PEPPER = b"pepper-test-procesar-carpeta-nunca-real"


def _cargar_script():
    """Carga `scripts/procesar_carpeta.py` por ruta -- `scripts/` no es un paquete instalado."""
    spec = importlib.util.spec_from_file_location("_procesar_carpeta_bajo_prueba", _RUTA_SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


@pytest.fixture(autouse=True)
def _resetear_fabrica_ejecutor():
    yield
    tareas._fabrica_ejecutor = None


def _grupo_completo(directorio, sufijo: str):
    """Los tres estudios de un mismo paciente sintético: un episodio completo.

    Prefijos numéricos en el nombre de archivo (no `lab-`/`ecg-`/`eco-` solos):
    `LanzadorCorrida` inventaría vía `FuenteLocal.listar()`, que orderna por
    `sorted(rglob("*"))` -- alfabético por ruta, no por orden de escritura.
    `procesar_lote` resuelve identidad en ESE orden, y el ECG (sin DNI) necesita
    el puente que solo registra el laboratorio (con DNI) al resolverse primero
    (`resolutor_claves.py::resolver_claves`). Sin el prefijo, "ecg-" ordena antes
    que "lab-" y el ECG cae en `CLAVE_PII_NO_RESUELTA` antes de que el
    laboratorio del mismo lote llegue a registrar el puente."""
    return [
        documentos.escribir_pdf(
            directorio,
            f"01-lab-{sufijo}",
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
            f"02-ecg-{sufijo}",
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
            f"03-eco-{sufijo}",
            documentos.texto_eco(
                nombre="Ana Sintetica Grupo",
                dni="20555888",
                numero_estudio=f"ECO-{sufijo}",
                fecha="12/01/2024",
            ),
        ),
    ]


def test_el_script_usa_lanzador_corrida_y_propaga_corrida_id_hasta_el_procesamiento(
    tmp_path, motor: MotorPii
) -> None:
    """6.8: falla hoy -- el script arma `FuenteLocal`/`ItemLote` a mano y llama
    `ejecutor.procesar_lote(items)` sin ningún `corrida_id`, así que no existe
    ninguna fila `corrida` ni `corrida_id` en `estudio` al terminar."""
    _grupo_completo(tmp_path, "s1")

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER)

    assert codigo == 0
    with Session(engine) as sesion:
        corridas = sesion.scalars(sa.select(CorridaOrm)).all()
        assert len(corridas) == 1, "el script debe lanzar la corrida vía LanzadorCorrida"

        estudios = sesion.scalars(sa.select(Estudio)).all()
    assert len(estudios) == 3
    assert all(
        estudio.corrida_id == corridas[0].id_corrida for estudio in estudios
    ), "corrida_id debe llegar hasta el procesamiento real, no quedar en None"


def test_el_apartado_por_sobretamano_antes_de_la_huella_queda_atribuido_a_la_corrida(
    tmp_path, motor: MotorPii
) -> None:
    """Punta a punta desde el script: `FuenteLocal._apartar_por_sobretamano` corre
    ANTES de calcular el sha256, así que ese artefacto nunca puede inventariarse
    ni pasar por `_a_fallo` -- el único otro punto donde el `corrida_id` está en
    mano. Sin `CuarentenaDeCorrida` (justificación en `lanzador_corrida.py`),
    esta fila de cuarentena quedaría con `corrida_id=None`."""
    _grupo_completo(tmp_path, "s2")
    # Los PDFs sintéticos de `_grupo_completo` rondan ~1 KB (texto real vía
    # reportlab/pymupdf): el tope va bien por encima de eso y el "gigante" bien
    # por debajo del default de producción (50 MB) pero muy por encima del tope.
    (tmp_path / "04-gigante.pdf").write_bytes(b"X" * 20_000)

    modulo = _cargar_script()
    engine = sa.create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    codigo = modulo.ejecutar(entrada=tmp_path, engine=engine, motor=motor, pepper=PEPPER, tope_bytes=5_000)

    assert codigo == 0
    with Session(engine) as sesion:
        (corrida,) = sesion.scalars(sa.select(CorridaOrm)).all()
        cuarentenas_por_sobretamano = sesion.scalars(
            sa.select(Cuarentena).where(Cuarentena.codigo == CodigoErrorDocumento.ARTEFACTO_SOBRETAMANO.value)
        ).all()

    assert len(cuarentenas_por_sobretamano) == 1
    assert cuarentenas_por_sobretamano[0].corrida_id == corrida.id_corrida
