"""Centinela de regresión: el fixture PARSEABLE (ver `esqueleto.py`, sección
"Fixture PARSEABLE") sustituye contenido por valores SINTÉTICOS en vez de
taparlo por forma. Es una superficie de riesgo más peligrosa que el esqueleto
enmascarado (ver `test_centinela_esqueletos.py`): acá SÍ hay contenido con
forma de dato real -- nombres, fechas, números de documento --, así que un
bug puntual en la sustitución podría dejar un valor REAL del paciente tal
cual en un archivo versionado, indistinguible a simple vista de uno
sintético.

ESTE ES EL TEST MÁS IMPORTANTE DE LA TAREA.

**Por qué los valores prohibidos NO están escritos acá.** La primera versión
de este centinela declaraba el nombre, el DNI y la fecha de nacimiento del
paciente real en una constante, con el argumento de que era seguro porque el
propósito del test es justamente probar que no aparecen. Ese argumento es
falso: el proyecto entero existe para que el nombre y el documento de un
paciente no salgan de la custodia del instituto, y un archivo versionado que
los contiene es una divulgación completa, sin importar qué diga el
comentario que los rodea -- además de quedar en el historial de git para
siempre. Tampoco alcanzaría con guardar hashes: el propio `claves.py`
documenta que el espacio de DNIs es enumerable y que un hash simple es
reversible por fuerza bruta, que es exactamente el motivo por el que la
pseudonimización del pipeline usa HMAC con un pepper secreto.

**Qué se hace en su lugar.** Los valores prohibidos se DERIVAN de los PDFs
reales en tiempo de test, con los mismos parsers de producción. El
repositorio no contiene ninguna representación de ellos, y el test es además
más fuerte que la versión anterior: en vez de una lista fija que alguien
tendría que mantener a mano, afirma la propiedad general **"nada de lo que
el propio sistema considera identidad puede sobrevivir a la sustitución"**,
sobre cualquier PDF que se deje en la carpeta.

Se usa `glob` en vez de nombres de archivo: los nombres no aportan al test
(cualquier PDF de esa carpeta debe cumplir la misma propiedad) y así no
queda atado a que alguien renombre o agregue una cuarta muestra.

Se salta (`skipif`) en cualquier máquina que no tenga los PDFs reales en
`D:\\ejemplos_pdf\\`: son PII real y nunca viajan con el repositorio, así que
este test sólo corre donde los fixtures se generan -- que es exactamente
donde una fuga podría introducirse.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import pytest

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.esqueleto import (
    ALLOWLIST_ESTRUCTURAL,
    generar_esqueleto,
    generar_fixture_parseable,
)
from anonimizacion.extraccion.texto_pymupdf import extraer_texto
from anonimizacion.parseo.registro import obtener_parseador

_RUTA_PDFS_REALES = Path(r"D:\ejemplos_pdf")

# Longitud mínima de un fragmento para exigir que no aparezca. Por debajo de
# esto la coincidencia sería casual: las palabras sintéticas se arman con
# letras al azar y contienen trigramas de cualquier apellido con alta
# probabilidad (comprobado: "xyz" aparece dentro de "oxyzegukimacoc").
_LONGITUD_MINIMA_FRAGMENTO = 4

# Texto institucional que el instituto imprime cuando un campo NO tiene
# valor: el laboratorio escribe "SIN MEDICO DERIVANTE" y el eco escribe
# "LIBRE" en el campo de medico solicitante. Son marcadores de ausencia,
# no nombres de persona, y ademas "MEDICO" coincide con la etiqueta
# "Medico:" que el fixture parseable conserva por diseno para que el
# parser pueda anclar el campo. Sin esta exclusion el centinela dispara
# sobre su propia etiqueta y se vuelve ruido que alguien terminaria
# desactivando -- peor que no tenerlo.
#
# Es la unica lista escrita a mano de este modulo, y se acepta porque
# ninguna de estas palabras identifica a nadie: si el dia de manana un
# documento trae un medico derivante REAL, su apellido no esta aca y si
# se comprueba. El nombre del medico informante (la firma al pie) tampoco
# pasa por esta exclusion.
_MARCADORES_DE_AUSENCIA = frozenset({"SIN", "MEDICO", "DERIVANTE", "LIBRE"})

_MESES_EN_INGLES = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _normalizar(texto: str) -> str:
    return _sin_acentos(texto).upper()


def _palabras_estructurales() -> frozenset[str]:
    """Palabras que el enmascarador preserva a propósito por ser estructura.

    Un token que `esqueleto.py` conserva como etiqueta no puede tratarse como
    identidad: la etiqueta `Médico:` sobrevive en todo fixture por diseño, y
    el campo `medico_derivante` de estos documentos trae el texto
    institucional `SIN MEDICO DERIVANTE` -- un marcador de ausencia, no el
    nombre de una persona. Sin esta exclusión el centinela dispara sobre su
    propia etiqueta y se vuelve ruido que alguien terminaría desactivando.

    Se deriva de `ALLOWLIST_ESTRUCTURAL`, no de una lista escrita a mano, para
    que no se desincronice si mañana se agrega o quita una etiqueta.
    """
    palabras: set[str] = set()
    for entrada in ALLOWLIST_ESTRUCTURAL:
        palabras.update(re.split(r"[^A-Za-z0-9]+", _normalizar(entrada)))
    return frozenset(palabra for palabra in palabras if palabra)


def _variantes_de_fecha(iso: str) -> tuple[str, ...]:
    """Las formas en que una fecha ISO parseada aparece en los documentos reales.

    El parser normaliza a `AAAA-MM-DD`, pero el laboratorio la imprime como
    `DD/MM/AAAA` y el ECG como `DD-MMM-AAAA` en inglés. Buscar sólo la forma
    normalizada dejaría pasar justamente la que está escrita en el PDF.
    """
    try:
        valor = date.fromisoformat(iso[:10])
    except ValueError:
        return (iso,)
    return (
        iso,
        f"{valor.day:02d}/{valor.month:02d}/{valor.year}",
        f"{valor.day:02d}-{_MESES_EN_INGLES[valor.month - 1]}-{valor.year}",
        f"{valor.day:02d}.{valor.month:02d}.{valor.year}",
    )


def _despiezar(crudos: list[str]) -> frozenset[str]:
    """El valor entero y cada una de sus palabras, filtrando las muy cortas.

    El nombre completo casi nunca sobrevive entero a una fuga parcial, pero un
    apellido suelto sí.
    """
    fragmentos: set[str] = set()
    for crudo in crudos:
        fragmentos.add(crudo.strip())
        fragmentos.update(re.split(r"[\s,]+", crudo))
    return frozenset(f for f in fragmentos if len(f) >= _LONGITUD_MINIMA_FRAGMENTO)


def _identidad_del_paciente(pdf: Path) -> frozenset[str]:
    """NÚCLEO DURO: nombre, DNI y fecha de nacimiento del paciente.

    Se comprueba SIN NINGUNA EXCEPCIÓN, en los dos fixtures. Estos tres datos
    nunca pueden ser una etiqueta estructural ni texto institucional, así que
    cualquier coincidencia es una fuga real. Son además los únicos que el
    proyecto define como prohibidos de publicar (ver la decisión sobre
    cuasi-identificadores en la nota de arquitectura).
    """
    texto = extraer_texto(pdf)
    documento = obtener_parseador(detectar_tipo(texto)).parsear(texto)
    identidad = documento.identidad

    crudos: list[str] = [identidad.nombre.get_secret_value()]
    if identidad.dni is not None:
        crudos.append(identidad.dni.get_secret_value())
    if identidad.fecha_nac is not None:
        crudos.extend(_variantes_de_fecha(identidad.fecha_nac.get_secret_value()))
    return _despiezar(crudos)


def _identificatorios_secundarios(pdf: Path) -> frozenset[str]:
    """Médico derivante, firma, matrícula e identificadores internos.

    A diferencia del núcleo duro, acá SÍ se excluyen las palabras que el
    enmascarador preserva como estructura. El motivo es concreto: el campo
    `medico_derivante` de estos documentos trae el texto institucional
    `SIN MEDICO DERIVANTE` -- un marcador de ausencia, no el nombre de una
    persona -- y su palabra `MEDICO` coincide con la etiqueta `Médico:` que
    todo fixture conserva por diseño. Sin la exclusión el centinela dispara
    sobre su propia etiqueta y se vuelve ruido que alguien terminaría
    desactivando, que es peor que no tenerlo.

    El riesgo de la exclusión es acotado y conocido: si el enmascarador
    filtrara un apellido, esa palabra quedaría excluida acá. Por eso el
    NÚCLEO DURO -- que es donde vive el apellido del paciente -- no admite
    ninguna exclusión.
    """
    texto = extraer_texto(pdf)
    documento = obtener_parseador(detectar_tipo(texto)).parsear(texto)

    crudos: list[str] = [
        interno.get_secret_value() for interno in documento.identidad.ids_internos
    ]
    for clave in ("medico_derivante", "medico_solicitante"):
        valor = documento.adicionales.get(clave)
        if valor:
            crudos.append(str(valor))

    firma = getattr(documento.contenido, "firma", None)
    if firma is not None:
        for atributo in ("nombre", "matricula"):
            valor = getattr(firma, atributo, None)
            if valor:
                crudos.append(str(valor))

    excluidas = _palabras_estructurales() | _MARCADORES_DE_AUSENCIA
    return frozenset(
        fragmento
        for fragmento in _despiezar(crudos)
        if _normalizar(fragmento) not in excluidas
    )


@pytest.mark.skipif(
    not _RUTA_PDFS_REALES.is_dir(),
    reason=f"requiere los PDFs reales en '{_RUTA_PDFS_REALES}' (nunca versionados, ver .gitignore)",
)
def test_ningun_dato_identificatorio_real_sobrevive_a_la_sustitucion() -> None:
    """Si esto falla, un dato real de un paciente puede terminar versionado en git."""
    pdfs = sorted(_RUTA_PDFS_REALES.glob("*.pdf"))
    assert pdfs, f"'{_RUTA_PDFS_REALES}' existe pero no tiene ningun PDF"

    for pdf in pdfs:
        nucleo = _identidad_del_paciente(pdf)
        secundarios = _identificatorios_secundarios(pdf)
        assert nucleo, f"no se derivo identidad de paciente de '{pdf.name}'"

        texto = extraer_texto(pdf)
        salidas = {
            "PARSEABLE": generar_fixture_parseable(texto).formatear(),
            "ENMASCARADO": generar_esqueleto(texto).formatear(),
        }
        for etiqueta, salida in salidas.items():
            # Sin acentos y en mayusculas: una sustitucion que solo cambiara la
            # tilde o la caja no debe contar como proteccion.
            comparable = _normalizar(salida)
            for nivel, fragmentos in (("NUCLEO", nucleo), ("SECUNDARIO", secundarios)):
                for fragmento in fragmentos:
                    patron = re.compile(
                        r"(?<![A-Z0-9])" + re.escape(_normalizar(fragmento)) + r"(?![A-Z0-9])"
                    )
                    assert not patron.search(comparable), (
                        f"un identificatorio de nivel {nivel} de '{pdf.name}' sobrevivio "
                        f"en el fixture {etiqueta} -- PII real filtrada. El valor no se "
                        f"reproduce en este mensaje a proposito."
                    )


@pytest.mark.skipif(
    not _RUTA_PDFS_REALES.is_dir(),
    reason=f"requiere los PDFs reales en '{_RUTA_PDFS_REALES}' (nunca versionados, ver .gitignore)",
)
def test_los_fixtures_versionados_coinciden_con_los_que_genera_el_codigo_actual() -> None:
    """Los `.txt` del repo deben ser reproducibles desde los PDFs reales.

    Si alguien edita un fixture a mano -- por ejemplo para "arreglar" un test
    de parseo que empezó a fallar -- este test lo detecta. Sin él, un fixture
    editado a mano podría enmascarar exactamente la regresión que los fixtures
    existen para atrapar.
    """
    raiz = Path(__file__).resolve().parents[1] / "fixtures"
    # El fixture se ubica por el TIPO detectado, nunca por el nombre del
    # archivo: los nombres de los PDFs reales son numeros de peticion y de
    # estudio del instituto -- datos de registro que no deben quedar
    # versionados, ni siquiera como nombre de archivo en un test.
    prefijo_por_tipo = {
        TipoDocumento.LABORATORIO: "laboratorio",
        TipoDocumento.ECOCARDIOGRAMA: "eco",
        TipoDocumento.ECG: "ecg",
    }
    for pdf in sorted(_RUTA_PDFS_REALES.glob("*.pdf")):
        texto = extraer_texto(pdf)
        prefijo = prefijo_por_tipo.get(detectar_tipo(texto))
        if prefijo is None:
            continue
        for carpeta, generar in (
            ("esqueletos", generar_esqueleto),
            ("parseables", generar_fixture_parseable),
        ):
            versionado = (raiz / carpeta / f"{prefijo}-01.txt").read_text(encoding="utf-8")
            assert generar(texto).formatear() == versionado, (
                f"'{carpeta}/{prefijo}-01.txt' no coincide con lo que genera el código "
                f"actual: o se editó a mano, o cambió el generador sin regenerarlo"
            )
