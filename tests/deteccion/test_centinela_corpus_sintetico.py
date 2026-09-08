"""Centinela: el corpus sintético (`tests/fixtures/pdf_sintetico.py` +
`tests/fixtures/v1/documentos.py`) declara EXACTAMENTE los marcadores y
títulos de sección estructurales que el documento REAL trae -- ni uno de más
(inventado), ni uno de menos (faltante).

Motivo de este test (tarea "regenerar corpus sintético desde layouts
reales"): el repo lleva nueve instancias documentadas del mismo defecto --
`deteccion/firmas/eco_doppler.py` y `deteccion/firmas/ecg_mortara.py`
declaraban marcadores que salían de un corpus sintético inventado por
nosotros y nunca aparecían en un documento real (ver docstrings de esos dos
módulos). Sin un test que lo custodie, nada impide que vuelva a pasar la
semana que viene con un layout nuevo.

DISEÑO -- universo de comparación cerrado y derivado de producción: en vez
de comparar "cualquier palabra" entre el sintético y el real (ruidoso, y
tentador de completar a mano), este centinela sólo compara el vocabulario
que la propia producción ya declara como estructuralmente significativo:
- los marcadores de cada `Firma` (`deteccion/firmas/*.py`),
- los prefijos literales de `_CAMPOS_HEADER` de cada parser (mismo criterio
  que ya usa `esqueleto.py::ALLOWLIST_ESTRUCTURAL`),
- los títulos de sección/subsección del eco (`_SECCIONES_TEXTO`,
  `_SUBSECCIONES`, `_SECCION_MEDIDAS` de `parseo/eco_doppler.py`),
- las secciones de laboratorio (`SECCIONES_LABORATORIO` de
  `parseo/contrato_laboratorio.py`),
- las etiquetas de medida de ECG que no son marcador de firma
  (`esqueleto._ETIQUETAS_MEDIDA_ECG`).

Ese universo es exactamente lo que un refactor de firma/parser podría
descalibrar en silencio -- es la misma superficie que ya protege
`test_centinela_esqueletos.py` (detección) y `test_centinela_fixtures_
parseables.py` (fixtures versionados), aplicada acá al TERCER lado del
triángulo: el generador de PDFs sintéticos que alimenta los escalones de
carga y la mayoría de los 884 tests.

"REAL" se define acá como "aparece literalmente en `tests/fixtures/
parseables/<tipo>-01.txt`" -- el fixture parseable preserva TODAS las
etiquetas estructurales de la allowlist (incluidas las de sección, que el
esqueleto enmascarado no protege) con sus valores sustituidos por datos
sintéticos, así que es superset seguro sin exponer ningún dato real (ver
`esqueleto.py`, sección "Fixture PARSEABLE").

EXCEPCIONES -- documentadas a mano, a propósito: un puñado de marcadores NO
verificados contra el documento real se conservan por una razón concreta ya
registrada en el código de producción (no por descuido). Agregar uno nuevo a
esta lista sin justificación es exactamente el defecto que este test existe
para atrapar -- por eso están acá, visibles, en vez de en un `try/except`
silencioso.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from anonimizacion.deteccion.firmas import FIRMAS
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.esqueleto import _ETIQUETAS_MEDIDA_ECG, _prefijo_literal
from anonimizacion.parseo.contrato_laboratorio import SECCIONES_LABORATORIO
from anonimizacion.parseo.ecg_mortara import _CAMPOS_HEADER as _HEADER_ECG
from anonimizacion.parseo.eco_doppler import _CAMPOS_HEADER as _HEADER_ECO
from anonimizacion.parseo.eco_doppler import _SECCION_MEDIDAS, _SECCIONES_TEXTO, _SUBSECCIONES
from anonimizacion.parseo.laboratorio_general import _CAMPOS_HEADER as _HEADER_LAB
from tests.fixtures.pdf_sintetico import generar_corpus_clinico
from tests.fixtures.v1 import documentos as v1

_DIRECTORIO_PARSEABLES = Path(__file__).parent.parent / "fixtures" / "parseables"

# "MORTARA" (ECG): el equipo real de este layout no imprimió el nombre de
# marca en la única muestra capturada -- ver docstring de
# `firmas/ecg_mortara.py`. Se conserva porque podría aparecer en otra
# variante de reporte del mismo equipo (p. ej. otro pie de página) y no hace
# daño mantenerlo: `Firma.puntaje` ya no depende de un solo marcador.
#
# "QUIMICA CLINICA" sin tilde (laboratorio): es la forma CANÓNICA interna
# (`contrato_laboratorio.SECCIONES_LABORATORIO`, que normaliza acentos antes
# de comparar) -- el documento real imprime la forma acentuada
# ("QUÍMICA CLÍNICA", ya verificada y declarada como marcador). Cambiar las
# ~14 referencias del repo a la forma acentuada es un refactor de blast
# radius mucho mayor que el de "ECOCARDIOGRAMA DOPPLER" (que sólo tenía 3) y
# de valor marginal -- ambas formas ya normalizan al mismo canónico en
# producción. Se documenta acá como decisión consciente, no como omisión.
_EXCEPCIONES_NO_VERIFICADAS: dict[TipoDocumento, frozenset[str]] = {
    TipoDocumento.ECG: frozenset({"MORTARA"}),
    TipoDocumento.LABORATORIO: frozenset({"QUIMICA CLINICA"}),
    TipoDocumento.ECOCARDIOGRAMA: frozenset(),
}


def _candidatos_estructurales(tipo: TipoDocumento) -> frozenset[str]:
    """Universo de etiquetas/marcadores estructurales declarados por producción
    para `tipo` -- ver docstring del módulo, sección DISEÑO."""
    (firma,) = [f for f in FIRMAS if f.tipo is tipo]
    candidatos: set[str] = set(firma.marcadores)

    if tipo is TipoDocumento.ECG:
        candidatos.update(p for p in (_prefijo_literal(pat) for pat in _HEADER_ECG.values()) if p)
        candidatos.update(_ETIQUETAS_MEDIDA_ECG)
    elif tipo is TipoDocumento.ECOCARDIOGRAMA:
        candidatos.update(p for p in (_prefijo_literal(pat) for pat in _HEADER_ECO.values()) if p)
        candidatos.update(_SECCIONES_TEXTO)
        candidatos.add(_SECCION_MEDIDAS)
        for subsecciones in _SUBSECCIONES.values():
            candidatos.update(subsecciones)
    elif tipo is TipoDocumento.LABORATORIO:
        candidatos.update(p for p in (_prefijo_literal(pat) for pat in _HEADER_LAB.values()) if p)
        candidatos.update(SECCIONES_LABORATORIO)

    return frozenset(candidatos)


def _nombre_fixture(tipo: TipoDocumento) -> str:
    return {"ecg": "ecg", "ecocardiograma": "eco", "laboratorio": "laboratorio"}[tipo.value]


def _vocabulario_real_verificado(tipo: TipoDocumento) -> frozenset[str]:
    """Subconjunto de `_candidatos_estructurales(tipo)` que aparece
    literalmente en el fixture parseable real (ver docstring, sección
    "REAL")."""
    texto = (_DIRECTORIO_PARSEABLES / f"{_nombre_fixture(tipo)}-01.txt").read_text(encoding="utf-8").upper()
    return frozenset(c for c in _candidatos_estructurales(tipo) if c.upper() in texto)


def _texto_pdf_sintetico(tipo: TipoDocumento, tmp_path: Path) -> str:
    corpus = generar_corpus_clinico(tmp_path, semilla=101)
    ruta = next(doc.ruta for doc in corpus.documentos if doc.tipo == tipo.value)
    documento = pymupdf.open(ruta)
    try:
        # Ambos órdenes: un marcador de ECG puede sobrevivir sólo en el de
        # dibujado (ver docstring de `extraccion/texto_pymupdf.py`).
        return "\n".join(
            pagina.get_text("text", sort=sort) for pagina in documento for sort in (False, True)
        )
    finally:
        documento.close()


def _texto_v1_documentos(tipo: TipoDocumento) -> str:
    """Texto del generador LEGADO (`fixtures/v1/documentos.py`) para `tipo`,
    con sus parámetros por defecto -- es texto plano, no hace falta
    renderizar ni extraer un PDF."""
    generadores = {
        TipoDocumento.ECG: lambda: v1.texto_ecg(
            nombre="Paciente Sintetico V1", id_estudio="ID-SINT-1", fecha="15-JAN-2024", fecha_nac="15-JAN-1980", edad_anios=44
        ),
        TipoDocumento.LABORATORIO: lambda: v1.texto_laboratorio(
            nombre="Paciente Sintetico V1", dni="30111222", fecha_nac="15/01/1980", numero_peticion="PET-SINT-1", fecha="15/01/2024"
        ),
        TipoDocumento.ECOCARDIOGRAMA: lambda: v1.texto_eco(
            nombre="Paciente Sintetico V1", dni="30111222", numero_estudio="ECO-SINT-1", fecha="15/01/2024"
        ),
    }
    return "\n".join(generadores[tipo]())


_CASOS = (
    pytest.param(TipoDocumento.ECG, id="ecg"),
    pytest.param(TipoDocumento.ECOCARDIOGRAMA, id="ecocardiograma"),
    pytest.param(TipoDocumento.LABORATORIO, id="laboratorio"),
)


@pytest.mark.parametrize("tipo", _CASOS)
def test_corpus_sintetico_no_inventa_marcadores_no_verificados(tipo: TipoDocumento, tmp_path: Path) -> None:
    """El sintético no puede usar un marcador/etiqueta que el documento real
    NO tiene, salvo una excepción documentada a mano (ver
    `_EXCEPCIONES_NO_VERIFICADAS`)."""
    verificados = _vocabulario_real_verificado(tipo)
    permitidos = verificados | _EXCEPCIONES_NO_VERIFICADAS[tipo]
    texto_sintetico = (_texto_pdf_sintetico(tipo, tmp_path) + "\n" + _texto_v1_documentos(tipo)).upper()

    usados = {c for c in _candidatos_estructurales(tipo) if c.upper() in texto_sintetico}
    inventados = sorted(usados - permitidos)
    assert not inventados, (
        f"el corpus sintetico de '{tipo.value}' usa marcador(es) que NO aparecen en el documento "
        f"real y no tienen excepcion documentada: {inventados}"
    )


@pytest.mark.parametrize("tipo", _CASOS)
def test_corpus_sintetico_no_le_falta_ningun_marcador_verificado_real(tipo: TipoDocumento, tmp_path: Path) -> None:
    """El sintético tiene que reproducir TODO marcador/etiqueta que sí está
    verificado contra el documento real -- si falta uno, el corpus dejó de
    ejercitar esa parte del layout real."""
    verificados = _vocabulario_real_verificado(tipo)
    texto_sintetico = (_texto_pdf_sintetico(tipo, tmp_path) + "\n" + _texto_v1_documentos(tipo)).upper()

    faltantes = sorted(m for m in verificados if m.upper() not in texto_sintetico)
    assert not faltantes, (
        f"el corpus sintetico de '{tipo.value}' no reproduce marcador(es) verificados contra el "
        f"documento real: {faltantes}"
    )


def test_ecocardiograma_doppler_no_es_marcador_de_firma() -> None:
    """Regresión concreta de esta tarea: "ECOCARDIOGRAMA DOPPLER" nunca
    aparece en el documento real (ver docstring de `firmas/eco_doppler.py`)
    y ya no tiene ningún fixture que dependa de él -- si alguien lo
    reintroduce en la firma, este test lo marca de inmediato."""
    (firma_eco,) = [f for f in FIRMAS if f.tipo is TipoDocumento.ECOCARDIOGRAMA]
    assert "ECOCARDIOGRAMA DOPPLER" not in firma_eco.marcadores
