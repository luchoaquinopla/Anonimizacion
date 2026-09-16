"""Parser de laboratorio general.
PDFs multipágina con header repetido; reconcilia por Nº de Petición y falla si cambia entre
páginas en vez de mezclar resultados de dos pacientes.

Fix (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix: extracción con sort=True +
firmas ECG reales"): lee `texto.paginas_ordenadas` (orden geométrico), no `texto.paginas`;
cada campo se trunca en el primer separador de 2+ espacios (`_primer_segmento`).

Fix #4 (recalibración lab/eco contra 3 documentos reales, misma sección de apply-progress):
tres variantes de etiqueta no contempladas (`F.Nacimiento :`, `Médico:`, `Hora de
Extracción:`); `_CAMPOS_HEADER` tolera espacio opcional y palabras intermedias, backward
compatible. Calibrado contra una sola muestra.

Fix #6 (cuerpo real de resultados, misma sección): el fix #4 sólo calibró el header; el
cuerpo seguía asumiendo el formato `|` sintético (0 filas reales). `_extraer_resultados`
reconoce también columnas por 2+ espacios, clasificando unidad/rango por forma del token.

Fix post-merge (sección "Fix: persistencia del puente id_alt_paciente en Postgres entre
corridas"): reconstruye un nombre de prueba partido en dos líneas por un paréntesis sin
cerrar (`_completar_nombre_partido`), heurística conservadora que sólo actúa con paréntesis
desbalanceado. Calibrado contra una sola muestra real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time

from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, DetalleParseoIncompleto, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.contrato_laboratorio import (
    SECCIONES_LABORATORIO,
    es_encabezado_documento_laboratorio,
    es_resultado_cualitativo_estructurado,
    normalizar_seccion_laboratorio,
)
from anonimizacion.reconciliacion.base import ReferenciaCampo
from anonimizacion.reconciliacion.normalizacion import normalizar_hora_iso

_ETAPA = "parseo"
_VERSION_ESQUEMA = 1

_PATRON_VALOR_FILA = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_PATRON_RANGO_REFERENCIA = re.compile(r"^[+-]?\d+(?:[.,]\d+)?\s*-\s*[+-]?\d+(?:[.,]\d+)?$")

_CAMPOS_HEADER = {
    "nombre": r"Apellido y Nombre:\s*(.+)",
    "dni": r"DNI:\s*(.+)",
    "fecha_nac": r"F\.Nacimiento\s*:\s*(.+)",
    "edad": r"Edad:\s*(.+)",
    "medico_derivante": r"M[eé]dico(?:\s+derivante)?:\s*(.+)",
    "numero_peticion": r"N[ºo°]\s*Petici[oó]n:\s*(.+)",
    "fecha": r"Fecha:\s*(.+)",
    "hora_extraccion": r"Hora(?:\s+de)?\s+Extracci[oó]n:\s*(.+)",
    "origen": r"Origen:\s*(.+)",
}


@dataclass(frozen=True)
class ResultadoLaboratorio:
    """Una fila de resultado dentro de una sección (HEMATOLOGIA, etc.)."""

    seccion: str
    prueba: str
    resultado: str
    unidades: str | None
    valores_referencia: str | None


@dataclass(frozen=True)
class ContenidoLaboratorio:
    """Payload tipado de un documento de laboratorio ya reconciliado."""

    numero_peticion: str
    resultados: tuple[ResultadoLaboratorio, ...]


def _primer_segmento(texto: str) -> str:
    """Trunca en el primer salto de 2+ espacios (separador de columnas del reporte)."""
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _extraer_campos_header(pagina: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave, patron in _CAMPOS_HEADER.items():
        coincidencia = re.search(patron, pagina)
        if coincidencia:
            campos[clave] = _primer_segmento(coincidencia.group(1))
    return campos


def _validar_header_completo(header: dict[str, str] | None) -> dict[str, str]:
    """Distingue las tres causas de un header incompleto (sin Nº de Petición, sin nombre, sin fecha).
    Extraída de `parsear` para no superar el límite de complejidad ciclomática (`pyproject.toml`)."""
    if header is None:
        raise ErrorParseo(
            codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
            etapa=_ETAPA,
            detalle_parseo=DetalleParseoIncompleto.HEADER_AUSENTE,
        )
    if "nombre" not in header:
        raise ErrorParseo(
            codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
            etapa=_ETAPA,
            detalle_parseo=DetalleParseoIncompleto.NOMBRE_AUSENTE,
        )
    if "fecha" not in header:
        raise ErrorParseo(
            codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
            etapa=_ETAPA,
            detalle_parseo=DetalleParseoIncompleto.FECHA_AUSENTE,
        )
    return header


def _parsear_fecha(texto: str) -> date:
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def _parsear_hora_extraccion(texto: str) -> tuple[time, PrecisionHora]:
    """Normaliza `Hora de Extracción:` con `normalizar_hora_iso`.
    Cero inferencia: si no matchea ningún formato, el `ValueError` propaga hasta cuarentena."""
    hora_normalizada, precision = normalizar_hora_iso(texto.strip())
    formato = "%H:%M:%S" if precision is PrecisionHora.SEGUNDO else "%H:%M"
    return datetime.strptime(hora_normalizada, formato).time(), precision


def _parsear_fecha_nacimiento(texto: str) -> str | None:
    """Normaliza `F.Nacimiento` a ISO 8601 para que el puente `id_alt_paciente` sea canónico
    entre laboratorio (`DD/MM/YYYY`) y ECG (`DD-MON-YYYY`, ver `sdd/pdf-pii-anonymization/
    apply-progress`, sección "Fix: recalibración parser ECG contra layout real Mortara")."""
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _normalizar_encabezado_seccion(linea_limpia: str) -> str:
    """Normaliza una línea candidata a nombre de sección: quita acentos, guiones y mayusculiza."""
    return normalizar_seccion_laboratorio(linea_limpia)


def _es_encabezado_tabla_repetido(candidata: str) -> bool:
    """Encabezado de columnas repetido por página; ruido a ignorar, no sección ni resultado."""
    return "RESULTADO" in candidata and ("UNIDADES" in candidata or "REFERENCIA" in candidata)


def _es_subencabezado_seccion(linea_limpia: str, candidata: str) -> bool:
    """Heurística para sub-bloques (ver Fix #6 en el docstring del módulo): línea sin dígitos,
    sin `:`, íntegramente en mayúsculas y sólo letras/espacios/puntos."""
    if ":" in linea_limpia or any(caracter.isdigit() for caracter in linea_limpia):
        return False
    if linea_limpia != linea_limpia.upper():
        return False
    return bool(re.fullmatch(r"[A-Z\s.]+", candidata))


def _clasificar_columnas_extra(tokens: list[str]) -> tuple[str | None, str | None]:
    """Clasifica columnas después de nombre+valor: `"min - max"` es rango, el resto es unidad."""
    unidades: str | None = None
    valores_referencia: str | None = None
    for token in tokens:
        if _PATRON_RANGO_REFERENCIA.match(token):
            valores_referencia = token
        elif unidades is None:
            unidades = token
    return unidades, valores_referencia


def _es_linea_continuacion_de_nombre(linea_limpia: str) -> bool:
    """True si es candidata a ser el cierre de un nombre partido: paréntesis de cierre, no es otra fila válida."""
    if ")" not in linea_limpia:
        return False
    tokens = [token for token in re.split(r"\s{2,}", linea_limpia) if token]
    return not (len(tokens) >= 2 and _PATRON_VALOR_FILA.match(tokens[1]))


def _completar_nombre_partido(nombre_prueba: str, lineas: list[str], indice: int) -> tuple[str, int]:
    """Reconstruye un nombre partido en dos líneas por un paréntesis sin cerrar.
    `(nombre_completo, 1)` si balancea; `(nombre_prueba, 0)` sin cambios si no aplica (conservador)."""
    if nombre_prueba.count("(") <= nombre_prueba.count(")"):
        return nombre_prueba, 0
    if indice + 1 >= len(lineas):
        return nombre_prueba, 0
    siguiente_limpia = lineas[indice + 1].strip()
    if not siguiente_limpia or not _es_linea_continuacion_de_nombre(siguiente_limpia):
        return nombre_prueba, 0
    nombre_completo = f"{nombre_prueba} {siguiente_limpia}"
    if nombre_completo.count("(") != nombre_completo.count(")"):
        return nombre_prueba, 0  # no se balanceó -- no forzar la fusión
    return nombre_completo, 1


def _extraer_resultados(  # noqa: C901 -- deuda conocida, ver pyproject.toml
    pagina: str, seccion_inicial: str | None = None
) -> tuple[tuple[ResultadoLaboratorio, ...], str | None]:
    resultados: list[ResultadoLaboratorio] = []
    seccion_actual = seccion_inicial
    lineas = pagina.splitlines()
    indice = 0
    while indice < len(lineas):
        linea_limpia = lineas[indice].strip()
        if not linea_limpia:
            indice += 1
            continue
        candidata = _normalizar_encabezado_seccion(linea_limpia)

        if es_encabezado_documento_laboratorio(linea_limpia):
            indice += 1
            continue

        if _es_encabezado_tabla_repetido(candidata):
            indice += 1
            continue

        if candidata in SECCIONES_LABORATORIO:
            seccion_actual = candidata
            indice += 1
            continue

        # Formato legado (fixtures sintéticas): filas separadas por "|".
        if "|" in linea_limpia:
            if seccion_actual is None:
                indice += 1
                continue
            partes = [parte.strip() for parte in linea_limpia.split("|")]
            if len(partes) < 2:
                indice += 1
                continue
            unidades = partes[2] if len(partes) > 2 and partes[2] else None
            valores_referencia = partes[3] if len(partes) > 3 and partes[3] else None
            resultados.append(
                ResultadoLaboratorio(
                    seccion=seccion_actual,
                    prueba=partes[0],
                    resultado=partes[1],
                    unidades=unidades,
                    valores_referencia=valores_referencia,
                )
            )
            indice += 1
            continue

        # Formato real: columnas separadas por 2+ espacios, sin "|".
        tokens = [token for token in re.split(r"\s{2,}", linea_limpia) if token]
        if len(tokens) >= 2 and ":" not in tokens[0] and (
            _PATRON_VALOR_FILA.match(tokens[1])
            or (len(tokens) == 2 and es_resultado_cualitativo_estructurado(tokens[1]))
        ):
            if seccion_actual is not None:
                nombre_prueba, lineas_consumidas = _completar_nombre_partido(tokens[0], lineas, indice)
                unidades, valores_referencia = _clasificar_columnas_extra(tokens[2:])
                resultados.append(
                    ResultadoLaboratorio(
                        seccion=seccion_actual,
                        prueba=nombre_prueba,
                        resultado=tokens[1],
                        unidades=unidades,
                        valores_referencia=valores_referencia,
                    )
                )
                indice += 1 + lineas_consumidas
                continue
            indice += 1
            continue

        if seccion_actual is not None and _es_subencabezado_seccion(linea_limpia, candidata):
            seccion_actual = candidata
            indice += 1
            continue

        indice += 1

    return tuple(resultados), seccion_actual


class ParseadorLaboratorioGeneral:
    """Parser del layout de laboratorio general; reconcilia header multi-página."""

    tipo_documento = TipoDocumento.LABORATORIO

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        header: dict[str, str] | None = None
        pagina_header: int | None = None
        resultados: list[ResultadoLaboratorio] = []
        paginas_resultados: list[int] = []
        seccion_actual: str | None = None

        for numero_pagina, pagina in enumerate(texto.paginas_ordenadas, start=1):
            campos_pagina = _extraer_campos_header(pagina)
            numero_peticion_pagina = campos_pagina.get("numero_peticion")

            if numero_peticion_pagina:
                if header is None:
                    header = campos_pagina
                    pagina_header = numero_pagina
                elif numero_peticion_pagina != header.get("numero_peticion"):
                    raise ErrorParseo(
                        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
                        etapa=_ETAPA,
                        detalle_parseo=DetalleParseoIncompleto.NUMERO_PETICION_INCONSISTENTE,
                    )

            resultados_pagina, seccion_actual = _extraer_resultados(pagina, seccion_actual)
            resultados.extend(resultados_pagina)
            paginas_resultados.extend([numero_pagina] * len(resultados_pagina))

        header = _validar_header_completo(header)

        try:
            fecha_estudio = _parsear_fecha(header["fecha"])
        except ValueError as _exc:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
                etapa=_ETAPA,
                detalle_parseo=DetalleParseoIncompleto.FECHA_ILEGIBLE,
            ) from _exc

        hora_estudio: time | None = None
        precision_hora = PrecisionHora.AUSENTE
        if header.get("hora_extraccion"):
            try:
                hora_estudio, precision_hora = _parsear_hora_extraccion(header["hora_extraccion"])
            except ValueError as _exc:
                # Hora presente pero ilegible: cuarentena, no ausencia silenciosa.
                raise ErrorParseo(
                    codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO,
                    etapa=_ETAPA,
                    detalle_parseo=DetalleParseoIncompleto.HORA_ILEGIBLE,
                ) from _exc

        fecha_nac_normalizada = (
            _parsear_fecha_nacimiento(header["fecha_nac"]) if header.get("fecha_nac") else None
        )

        identidad = IdentidadCruda(
            nombre=SecretStr(header["nombre"]),
            dni=SecretStr(header["dni"]) if header.get("dni") else None,
            fecha_nac=SecretStr(fecha_nac_normalizada) if fecha_nac_normalizada else None,
            ids_internos=(
                (SecretStr(header["numero_peticion"]),)
                if header.get("numero_peticion")
                else ()
            ),
        )

        adicionales = {
            clave: valor
            for clave, valor in header.items()
            if clave not in ("nombre", "dni", "fecha_nac", "fecha", "numero_peticion", "hora_extraccion")
        }

        contenido = ContenidoLaboratorio(
            numero_peticion=header.get("numero_peticion", ""),
            resultados=tuple(resultados),
        )
        fuentes = (
            *(
                (ReferenciaCampo("laboratorio.hora_extraccion", pagina_header, "laboratorio.hora_extraccion"),)
                if hora_estudio is not None
                else ()
            ),
        ) + tuple(
            ReferenciaCampo(
                "laboratorio.resultado",
                paginas_resultados[ordinal],
                "laboratorio.resultado",
                ordinal,
            )
            for ordinal, resultado in enumerate(contenido.resultados)
        )

        return DocumentoParseado(
            tipo_documento=TipoDocumento.LABORATORIO,
            version_esquema=_VERSION_ESQUEMA,
            identidad=identidad,
            fecha_estudio=fecha_estudio,
            hora_estudio=hora_estudio,
            precision_hora=precision_hora,
            contenido=contenido,
            adicionales=adicionales,
            fuentes=fuentes,
        )
