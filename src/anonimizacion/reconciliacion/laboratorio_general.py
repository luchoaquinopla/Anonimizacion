"""Strategy de reconciliación para laboratorio general."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo, EtapaDocumento
from anonimizacion.dominio.modelos import DocumentoParseado
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.contrato_laboratorio import (
    SECCIONES_LABORATORIO,
    es_encabezado_documento_laboratorio,
    es_resultado_cualitativo_estructurado,
    normalizar_seccion_laboratorio,
)
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio

from ._comun import reconciliar_cobertura, reconciliar_referencias
from .base import HallazgoCobertura
from .normalizacion import normalizar_texto


_PATRON_NUMERO = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_PATRON_ENCABEZADO = re.compile(r"resultado", re.IGNORECASE)
_PATRON_ENCABEZADO_PAGINA = re.compile(
    r"^(?:fecha|hora|apellido y nombre|documento|dni|m[eé]dico|n[ºo°]\s*petici[oó]n)\s*:",
    re.IGNORECASE,
)
# Rótulo "Hora de Extracción:", ancla del inventario y de _asociacion_laboratorio.
_PATRON_ROTULO_HORA_EXTRACCION = re.compile(r"Hora(?:\s+de)?\s+Extracci[oó]n:\s*(.+)", re.IGNORECASE)
@dataclass(frozen=True)
class _FilaInventariada:
    """Fila transitoria, usada solo para comparar el PDF en memoria."""

    seccion: str
    prueba: str
    resultado: str
    unidades: str | None
    valores_referencia: str | None
    pagina: int


def _normalizar_seccion(linea: str) -> str:
    return normalizar_seccion_laboratorio(linea)


def _fila_desde_linea(linea: str, seccion: str, pagina: int) -> _FilaInventariada | None:
    if "|" in linea:
        partes = [parte.strip() for parte in linea.split("|")]
        if len(partes) < 2 or not partes[0] or not partes[1]:
            return None
        return _FilaInventariada(
            seccion, partes[0], partes[1],
            partes[2] if len(partes) > 2 and partes[2] else None,
            partes[3] if len(partes) > 3 and partes[3] else None,
            pagina,
        )

    partes = [parte.strip() for parte in re.split(r"\s{2,}", linea) if parte.strip()]
    if len(partes) < 2 or not (
        _PATRON_NUMERO.fullmatch(partes[1])
        or (len(partes) == 2 and es_resultado_cualitativo_estructurado(partes[1]))
    ):
        return None
    referencia = next((parte for parte in partes[2:] if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?\s*-\s*[+-]?\d+(?:[.,]\d+)?", parte)), None)
    unidad = next((parte for parte in partes[2:] if parte != referencia), None)
    return _FilaInventariada(seccion, partes[0], partes[1], unidad, referencia, pagina)


def _completar_nombre_partido(
    fila: _FilaInventariada, lineas: list[str], indice: int
) -> tuple[_FilaInventariada, int]:
    if "|" in lineas[indice] or fila.prueba.count("(") <= fila.prueba.count(")") or indice + 1 >= len(lineas):
        return fila, 0
    continuacion = lineas[indice + 1].strip()
    if not continuacion or _fila_desde_linea(continuacion, fila.seccion, fila.pagina) is not None:
        return fila, 0
    nombre_completo = f"{fila.prueba} {continuacion}"
    if nombre_completo.count("(") != nombre_completo.count(")"):
        return fila, 0
    return (
        _FilaInventariada(
            fila.seccion, nombre_completo, fila.resultado, fila.unidades, fila.valores_referencia, fila.pagina
        ),
        1,
    )


def _primer_segmento(texto: str) -> str:
    """Trunca en el primer salto de 2+ espacios (separador de columnas del reporte);
    misma convención que `parseo/laboratorio_general.py::_primer_segmento`."""
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _asociacion_laboratorio(referencia: object, esperado: str, pagina: str) -> bool:
    """Ancla `laboratorio.hora_extraccion` a su rótulo real: un valor de hora suelto puede
    aparecer 0 o varias veces en la página, así que se exige que siga al rótulo explícito."""
    selector = getattr(referencia, "selector")
    if selector != "laboratorio.hora_extraccion":
        return False
    coincidencia = _PATRON_ROTULO_HORA_EXTRACCION.search(pagina)
    if coincidencia is None:
        return False
    valor_pagina = normalizar_texto(_primer_segmento(coincidencia.group(1))).replace(",", ".")
    return valor_pagina == esperado


def _es_subseccion(linea: str, candidata: str) -> bool:
    return (
        ":" not in linea
        and not any(caracter.isdigit() for caracter in linea)
        and linea == linea.upper()
        and bool(re.fullmatch(r"[A-Z\s.]+", candidata))
    )


class ReconciliadorLaboratorioGeneral:
    tipo_documento = TipoDocumento.LABORATORIO

    def es_texto_permitido(self, texto: str) -> bool:
        """Ignora únicamente el encabezado visual repetido de la tabla."""
        texto_normalizado = normalizar_texto(texto)
        return bool(_PATRON_ENCABEZADO.search(texto_normalizado)) and (
            "unidades" in texto_normalizado or "referencia" in texto_normalizado
        )

    def _filas_inventariadas(self, texto: TextoExtraido) -> tuple[_FilaInventariada, ...]:
        filas: list[_FilaInventariada] = []
        seccion: str | None = None
        for pagina, contenido in enumerate(texto.paginas_ordenadas, start=1):
            lineas = contenido.splitlines()
            indice = 0
            while indice < len(lineas):
                linea_limpia = lineas[indice].strip()
                seccion_candidata = _normalizar_seccion(linea_limpia)
                if es_encabezado_documento_laboratorio(linea_limpia):
                    indice += 1
                    continue
                if seccion_candidata in SECCIONES_LABORATORIO:
                    seccion = seccion_candidata
                    indice += 1
                    continue
                if (
                    seccion is None
                    or self.es_texto_permitido(linea_limpia)
                    or _PATRON_ENCABEZADO_PAGINA.match(linea_limpia)
                ):
                    indice += 1
                    continue
                if _es_subseccion(linea_limpia, seccion_candidata):
                    seccion = seccion_candidata
                    indice += 1
                    continue
                fila = _fila_desde_linea(linea_limpia, seccion, pagina)
                if fila is not None:
                    fila, lineas_consumidas = _completar_nombre_partido(fila, lineas, indice)
                    filas.append(fila)
                    indice += 1 + lineas_consumidas
                    continue
                indice += 1
        return tuple(filas)

    def _hallazgos_hora_extraccion(self, texto: TextoExtraido) -> tuple[HallazgoCobertura, ...]:
        """Inventaría el rótulo "Hora de Extracción:" anclado, nunca un `HH:MM` suelto."""
        for pagina, contenido in enumerate(texto.paginas_ordenadas, start=1):
            if _PATRON_ROTULO_HORA_EXTRACCION.search(contenido):
                return (HallazgoCobertura("laboratorio.hora_extraccion", pagina, clase="header"),)
        return ()

    def inventariar(self, texto: TextoExtraido) -> tuple[HallazgoCobertura, ...]:
        """Inventaría filas clínicas desde el PDF sin consultar el parseo."""
        return self._hallazgos_hora_extraccion(texto) + tuple(
            HallazgoCobertura("laboratorio.resultado", fila.pagina, ordinal, "coleccion")
            for ordinal, fila in enumerate(self._filas_inventariadas(texto))
        )

    def _verificar_asociacion_filas(
        self, documento: DocumentoParseado, contenido: ContenidoLaboratorio, texto: TextoExtraido
    ) -> tuple[bool, tuple[str, ...]]:
        """Compara filas PDF vs. modelo. PDF con más filas es benigno (parser omitió
        algo real); PDF con menos es integridad y termina en `COBERTURA_INCOMPLETA`."""
        filas_pdf = self._filas_inventariadas(texto)
        if not filas_pdf:
            return False, ()
        if len(filas_pdf) > len(contenido.resultados):
            faltantes = len(filas_pdf) - len(contenido.resultados)
            return False, ("laboratorio.resultado",) * faltantes
        if len(filas_pdf) < len(contenido.resultados):
            pagina = filas_pdf[-1].pagina if filas_pdf else 1
            raise ErrorParseo(
                CodigoErrorDocumento.COBERTURA_INCOMPLETA,
                EtapaDocumento.RECONCILIACION,
                "laboratorio.resultado",
                pagina,
            )
        paginas_por_ordinal = {
            referencia.ordinal: referencia.pagina
            for referencia in documento.fuentes
            if referencia.id_campo == "laboratorio.resultado"
        }
        for ordinal, (fila_pdf, fila_modelo) in enumerate(zip(filas_pdf, contenido.resultados, strict=True)):
            if paginas_por_ordinal.get(ordinal) != fila_pdf.pagina:
                raise ErrorParseo(
                    CodigoErrorDocumento.COBERTURA_INCOMPLETA,
                    EtapaDocumento.RECONCILIACION,
                    "laboratorio.resultado",
                    fila_pdf.pagina,
                )
            esperada = (
                normalizar_texto(fila_pdf.seccion), normalizar_texto(fila_pdf.prueba),
                normalizar_texto(fila_pdf.resultado).replace(",", "."),
                normalizar_texto(fila_pdf.unidades or ""), normalizar_texto(fila_pdf.valores_referencia or ""),
            )
            recibida = (
                normalizar_texto(fila_modelo.seccion), normalizar_texto(fila_modelo.prueba),
                normalizar_texto(fila_modelo.resultado).replace(",", "."),
                normalizar_texto(fila_modelo.unidades or ""), normalizar_texto(fila_modelo.valores_referencia or ""),
            )
            if recibida != esperada:
                raise ErrorParseo(
                    CodigoErrorDocumento.VALOR_DISCREPANTE,
                    EtapaDocumento.RECONCILIACION,
                    "laboratorio.resultado",
                    fila_pdf.pagina,
                )
        return True, ()

    def reconciliar(self, documento: DocumentoParseado, texto: TextoExtraido) -> tuple[str, ...]:
        contenido = documento.contenido
        if not isinstance(contenido, ContenidoLaboratorio):
            raise TypeError("contenido laboratorio inválido")
        valores: dict[tuple[str, int], str] = {
            ("laboratorio.resultado", indice): fila.resultado for indice, fila in enumerate(contenido.resultados)
        }
        if documento.hora_estudio is not None:
            formato_hora = "%H:%M:%S" if documento.precision_hora is PrecisionHora.SEGUNDO else "%H:%M"
            valores[("laboratorio.hora_extraccion", 0)] = documento.hora_estudio.strftime(formato_hora)
        inventario = self.inventariar(texto)
        tiene_asociacion_estructurada = False
        campos_no_extraidos: tuple[str, ...] = ()
        if inventario:
            # Ordinal de laboratorio.resultado = posición secuencial, no id estable: si el conteo difiere, se excluye del cruce genérico y decide _verificar_asociacion_filas.
            filas_pdf = self._filas_inventariadas(texto)
            resultados_alineados = len(filas_pdf) == len(contenido.resultados)
            if resultados_alineados:
                cobertura_inventario, cobertura_documento = inventario, documento
            else:
                cobertura_inventario = tuple(
                    hallazgo for hallazgo in inventario if hallazgo.id_campo != "laboratorio.resultado"
                )
                cobertura_documento = replace(
                    documento,
                    fuentes=tuple(f for f in documento.fuentes if f.id_campo != "laboratorio.resultado"),
                )
            campos_no_extraidos += reconciliar_cobertura(cobertura_documento, cobertura_inventario)
            tiene_asociacion_estructurada, campos_de_filas = self._verificar_asociacion_filas(
                documento, contenido, texto
            )
            campos_no_extraidos += campos_de_filas

        # El validador anclado a hora_extraccion no puede compartir la misma llamada que resultado (_comun.py exige asociación válida para toda referencia); se llama dos veces con subconjuntos de fuentes.
        fuentes_hora = tuple(f for f in documento.fuentes if f.id_campo == "laboratorio.hora_extraccion")
        fuentes_resto = tuple(f for f in documento.fuentes if f.id_campo != "laboratorio.hora_extraccion")
        reconciliar_referencias(
            replace(documento, fuentes=fuentes_resto),
            texto,
            valores,
            ids_con_asociacion_estructurada={"laboratorio.resultado"} if tiene_asociacion_estructurada else (),
        )
        reconciliar_referencias(
            replace(documento, fuentes=fuentes_hora),
            texto,
            valores,
            validador_asociacion=_asociacion_laboratorio,
        )
        return campos_no_extraidos
