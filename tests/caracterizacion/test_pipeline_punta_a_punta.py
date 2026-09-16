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
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import CodigoErrorDocumento
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.ingesta.fuente import FuenteLocal
from anonimizacion.parseo.registro import obtener_parseador as _obtener_parseador_real
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pipeline.ejecutor import EjecutorPipeline, ItemLote
from anonimizacion.pipeline.resultado import FalloDocumento
from anonimizacion.pseudonimizacion.resolutor_claves import ResolutorClaves
from anonimizacion.salida.cuarentena import EscritorCuarentena
from anonimizacion.salida.destinos.postgres import EscritorPostgres
from anonimizacion.salida.modelos_orm import Cuarentena, Episodio, Estudio, MedicionEcg

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


def _obtener_parseador_con_vent_rate_corrupto(tipo: TipoDocumento):
    """Envuelve el parser ECG real y corrompe SÓLO el valor publicado de
    `vent_rate` DESPUÉS de parsear -- `fuentes` (las referencias de página
    que usa la reconciliación) queda intacta, apuntando al valor REAL que
    sigue escrito en el PDF. Simula la clase de defecto que la Entrega 1
    del proyecto de origen (señal de ECG invertida) ya demostró que puede
    pasar desapercibida: un valor publicado que no es el que el documento
    realmente dice. No fabrica un PDF con un mismatch a mano -- inyecta el
    fallo en el borde parser->reconciliación, que es la interfaz real que
    `reconciliar_referencias` está para vigilar.

    El valor corrupto es `"160"` -- el `PR interval` REAL del fixture
    (`tests/fixtures/v1/documentos.py::texto_ecg`), no un número inventado:
    aparece EXACTAMENTE una vez en la página (para no disparar el chequeo
    de `ocurrencias != 1`, que es un guardia DISTINTO del que este test
    quiere ejercitar) pero nunca junto a la etiqueta `Vent. rate` -- por
    eso `_asociacion_ecg` (el `validador_asociacion` real) lo rechaza HOY.
    """
    parseador_real = _obtener_parseador_real(tipo)
    if tipo is not TipoDocumento.ECG:
        return parseador_real

    class _ParseadorEcgConVentRateCorrupto:
        tipo_documento = TipoDocumento.ECG

        def parsear(self, texto):
            documento = parseador_real.parsear(texto)
            contenido_corrupto = replace(documento.contenido, vent_rate="160")
            return replace(documento, contenido=contenido_corrupto)

    return _ParseadorEcgConVentRateCorrupto()


def _procesar_lab_y_ecg_con_puente(tmp_path: Path, motor: MotorPii, engine: sa.Engine, *, obtener_parseador):
    """Un laboratorio (con DNI) + un ECG (sin DNI) del MISMO paciente, en el
    MISMO lote -- el laboratorio registra el puente `id_alt_paciente ->
    id_paciente` que el ECG necesita para resolver su identidad
    (`ResolutorClaves`, ver `tests/scripts/test_procesar_carpeta.py`,
    `_grupo_completo`). Sin el puente, el ECG se aparta en pseudonimización
    (`CLAVE_PII_NO_RESUELTA`) ANTES de llegar a reconciliación -- lo que
    enmascararía el resultado que este test quiere fijar.

    `nombre` deliberadamente NO contiene ninguna palabra de las etiquetas de
    medida ECG (`Vent`, `rate`, `PR`, `QRS`, `QT`, `axes`, `ID:`): un nombre
    como "Vent Rate ..." colisiona con el patrón de inventario de
    `ecg.vent_rate` (`reconciliacion/ecg_mortara.py::_PATRONES_INVENTARIO`) y
    produce una clave duplicada -- `COBERTURA_AMBIGUA` por un motivo
    completamente ajeno a la mutación que este test ejercita. Detectado
    reproduciendo el defecto de la fixture con un script aislado antes de
    fijar esta versión."""
    nombre = "Reconciliacion Vigilada"
    dni = "20666000"
    documentos.escribir_pdf(
        tmp_path,
        "01-lab",
        documentos.texto_laboratorio(
            nombre=nombre,
            dni=dni,
            fecha_nac="09/09/1985",
            numero_peticion="PET-reconciliacion",
            fecha="10/01/2024",
        ),
    )
    artefacto_ecg = documentos.escribir_pdf(
        tmp_path,
        "02-ecg",
        documentos.texto_ecg(
            nombre=nombre,
            id_estudio="ECG-reconciliacion",
            fecha="11-JAN-2024",
            fecha_nac="09-SEP-1985",
            edad_anios=38,
            sexo="Female",
        ),
    )
    artefacto_lab = documentos.escribir_pdf(
        tmp_path,
        "01-lab",
        documentos.texto_laboratorio(
            nombre=nombre,
            dni=dni,
            fecha_nac="09/09/1985",
            numero_peticion="PET-reconciliacion",
            fecha="10/01/2024",
        ),
    )

    ejecutor = EjecutorPipeline(
        resolutor=ResolutorClaves(),
        motor=motor,
        pepper=PEPPER,
        destino=EscritorPostgres(engine),
        cuarentena=EscritorCuarentena(engine),
        fuente=FuenteLocal(raices=(tmp_path,), directorio=tmp_path),
        obtener_parseador=obtener_parseador,
    )
    return ejecutor.procesar_lote(
        [
            ItemLote(id_documento="lab-reconciliacion", artefacto=artefacto_lab),
            ItemLote(id_documento="ecg-reconciliacion-corrupto", artefacto=artefacto_ecg),
        ]
    )


def test_un_vent_rate_publicado_sin_evidencia_real_hoy_se_aparta_por_valor_discrepante(
    tmp_path: Path, motor: MotorPii, engine_caracterizacion: sa.Engine
) -> None:
    """Escenario "el test detecta una regresión real" (Requisito 1) + Requisito 6,
    aplicado al Requisito 1 mismo: si la reconciliación aprobara un `vent_rate`
    que no está respaldado por el PDF, ESE valor terminaría publicado en
    `medicion_ecg` -- superficie observable, no estructura interna. HOY
    (`_comun.py` sin mutar) el pipeline lo detecta y lo aparta.

    Evidencia de la mutación (Requisito 1, escenario 2 + Requisito 6):
    deshabilitar el segundo chequeo de `reconciliar_referencias`
    (`_comun.py`, `if validador_asociacion is not None and not
    asociacion_valida: raise ...`) hace que ESTE test se ponga en rojo -- el
    ECG pasa de `FalloDocumento` a `ExitoDocumento` y `medicion_ecg` termina
    con una fila cuyo `vent_rate` es `"160"` (el valor real de `PR interval`,
    sin ninguna evidencia de que sea el `Vent. rate`). Documentado en
    apply-progress, no dejado como mutación permanente."""
    resultados = _procesar_lab_y_ecg_con_puente(
        tmp_path, motor, engine_caracterizacion, obtener_parseador=_obtener_parseador_con_vent_rate_corrupto
    )

    assert len(resultados) == 2
    resultado_ecg = next(r for r in resultados if r.id_documento == "ecg-reconciliacion-corrupto")
    assert isinstance(resultado_ecg, FalloDocumento), (
        "hoy el pipeline rechaza un `vent_rate` publicado sin evidencia real en el PDF"
    )
    assert resultado_ecg.error.codigo is CodigoErrorDocumento.VALOR_DISCREPANTE
    assert resultado_ecg.error.etapa == "reconciliacion"
    assert resultado_ecg.error.campo == "ecg.vent_rate"

    with Session(engine_caracterizacion) as sesion:
        assert sesion.scalars(sa.select(MedicionEcg)).first() is None, (
            "ningún vent_rate sin evidencia real debe llegar a publicarse"
        )
