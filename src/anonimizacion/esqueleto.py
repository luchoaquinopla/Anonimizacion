"""Genera un esqueleto de formato: fixture de texto sin PII a partir de un PDF real.
Diseño allowlist, no denylist: enmascara por forma salvo lo derivado de `FIRMAS`/`_CAMPOS_HEADER`."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.deteccion.firmas import FIRMAS
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido
from anonimizacion.parseo.ecg_mortara import _CAMPOS_HEADER as _CAMPOS_HEADER_ECG
from anonimizacion.parseo.eco_doppler import _CAMPOS_HEADER as _CAMPOS_HEADER_ECO
from anonimizacion.parseo.laboratorio_general import _CAMPOS_HEADER as _CAMPOS_HEADER_LAB

# Vocabulario cerrado y estable, nunca contenido de un documento: ninguna codifica identidad.
_UNIDADES_ESTRUCTURALES: tuple[str, ...] = (
    "mg/dL",
    "mg/dl",
    "meq/lt",
    "mEq/L",
    "mEq/l",
    "mm",
    "%",
    "ms",
    "seg",
    "BPM",
    "bpm",
    "g/dL",
    "m2",
    "mmHg",
)

# Caracteres de regex donde se detiene la extracción del prefijo literal de un patrón.
_META_REGEX = set("\\().[]{}|^$*+?")
_ESCAPABLES = set(".^$*+?{}[]()|\\")
_PATRON_FLAGS_INLINE = re.compile(r"^(?:\(\?[a-zA-Z]+\))+")


def _prefijo_literal(patron: str) -> str | None:
    """Extrae el prefijo literal de un patrón de regex; falla cerrado (descarta si es ambiguo)."""
    resto = _PATRON_FLAGS_INLINE.sub("", patron)
    literal: list[str] = []
    indice = 0
    while indice < len(resto):
        caracter = resto[indice]
        if caracter == "\\" and indice + 1 < len(resto) and resto[indice + 1] in _ESCAPABLES:
            literal.append(resto[indice + 1])
            indice += 2
            continue
        if caracter in _META_REGEX:
            break
        literal.append(caracter)
        indice += 1
    texto = "".join(literal).strip()
    return texto if len(texto) >= 2 else None


def _etiquetas_desde_campos_header(campos_header: dict[str, str]) -> tuple[str, ...]:
    prefijos = (_prefijo_literal(patron) for patron in campos_header.values())
    return tuple(etiqueta for etiqueta in prefijos if etiqueta)


def _marcadores_de_firmas() -> tuple[str, ...]:
    return tuple(marcador for firma in FIRMAS for marcador in firma.marcadores)


def _construir_allowlist() -> tuple[str, ...]:
    etiquetas = (
        _marcadores_de_firmas()
        + _etiquetas_desde_campos_header(_CAMPOS_HEADER_ECG)
        + _etiquetas_desde_campos_header(_CAMPOS_HEADER_ECO)
        + _etiquetas_desde_campos_header(_CAMPOS_HEADER_LAB)
        + _UNIDADES_ESTRUCTURALES
    )
    # Únicas, más largas primero: si dos etiquetas se solapan, la más específica gana.
    return tuple(sorted(set(etiquetas), key=len, reverse=True))


#: Vocabulario estructural completo, derivado de las constantes de producción.
ALLOWLIST_ESTRUCTURAL: tuple[str, ...] = _construir_allowlist()


def _patron_termino(etiqueta: str) -> str:
    """Límite de palabra sólo en los extremos alfanuméricos (evita enmascarar "Horacio")."""
    escapada = re.escape(etiqueta)
    prefijo = r"\b" if etiqueta[:1].isalnum() else ""
    sufijo = r"\b" if etiqueta[-1:].isalnum() else ""
    return f"{prefijo}{escapada}{sufijo}"


def _compilar_patron_allowlist(etiquetas: tuple[str, ...]) -> re.Pattern[str]:
    if not etiquetas:
        return re.compile(r"(?!)")  # patrón que nunca matchea nada
    return re.compile("|".join(_patron_termino(etiqueta) for etiqueta in etiquetas), re.IGNORECASE)


_PATRON_ALLOWLIST = _compilar_patron_allowlist(ALLOWLIST_ESTRUCTURAL)
# Corridas de letras o de dígitos; cada corrida se reemplaza como unidad para preservar su longitud.
_PATRON_FORMA = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


def _reemplazar_por_forma(coincidencia: re.Match[str]) -> str:
    token = coincidencia.group()
    relleno = "0" if token[0].isdigit() else "X"
    return relleno * len(token)


def enmascarar_por_forma(texto: str) -> str:
    """Enmascara todo el texto por forma, salvo los términos de la allowlist.
    Preserva espaciado, puntuación, saltos de línea y longitudes."""
    piezas: list[str] = []
    posicion = 0
    for coincidencia in _PATRON_ALLOWLIST.finditer(texto):
        piezas.append(_PATRON_FORMA.sub(_reemplazar_por_forma, texto[posicion : coincidencia.start()]))
        piezas.append(coincidencia.group())  # preservado tal cual, sin tocar
        posicion = coincidencia.end()
    piezas.append(_PATRON_FORMA.sub(_reemplazar_por_forma, texto[posicion:]))
    return "".join(piezas)


def _puntaje_de_tipo(tipo: TipoDocumento, texto_normalizado: str) -> tuple[int, int]:
    """`(marcadores que matchearon, total)`; `(0, 0)` si `tipo` es TIPO_NO_RECONOCIDO."""
    for firma in FIRMAS:
        if firma.tipo is tipo:
            return firma.puntaje(texto_normalizado), len(firma.marcadores)
    return 0, 0


@dataclass(frozen=True)
class Esqueleto:
    """Resultado de `generar_esqueleto`: texto enmascarado + evidencia de detección."""

    tipo_detectado: TipoDocumento
    puntaje: int
    total_marcadores: int
    paginas: tuple[str, ...]
    paginas_ordenadas: tuple[str, ...]

    def formatear(self) -> str:
        """Fixture de texto legible y versionable con ambas representaciones."""
        lineas = [
            "# esqueleto de formato -- generado con `anonimizacion esqueleto`",
            f"# tipo_detectado: {self.tipo_detectado.value}",
            f"# puntaje_firma: {self.puntaje}/{self.total_marcadores} marcadores",
            "",
        ]
        for numero, pagina in enumerate(self.paginas, start=1):
            lineas.append(f"## pagina {numero} (orden de dibujado)")
            lineas.append(pagina)
        for numero, pagina in enumerate(self.paginas_ordenadas, start=1):
            lineas.append(f"## pagina {numero} (orden geometrico)")
            lineas.append(pagina)
        return "\n".join(lineas)


def generar_esqueleto(texto: TextoExtraido) -> Esqueleto:
    """Genera el esqueleto: detecta el tipo y enmascara ambas representaciones de `texto`."""
    texto_normalizado = texto.texto_completo.upper()
    tipo_detectado = detectar_tipo(texto)
    puntaje, total_marcadores = _puntaje_de_tipo(tipo_detectado, texto_normalizado)
    return Esqueleto(
        tipo_detectado=tipo_detectado,
        puntaje=puntaje,
        total_marcadores=total_marcadores,
        paginas=tuple(enmascarar_por_forma(pagina) for pagina in texto.paginas),
        paginas_ordenadas=tuple(enmascarar_por_forma(pagina) for pagina in texto.paginas_ordenadas),
    )


# ---------------------------------------------------------------------------
# Fixture PARSEABLE: reusa la misma allowlist estructural, pero sustituye por un
# valor sintético PLAUSIBLE de la misma forma en vez de tapar por `X`/`0`.
# Determinismo: cada sustitución es función pura del token (hash SHA-256), nunca de
# su posición. Fechas/horas se detectan por forma y se sustituyen por una fecha/hora
# VÁLIDA, con coherencia nacimiento < estudio cuando el header lo permite.
# ---------------------------------------------------------------------------

_MESES_INGLES_ABREVIADOS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)

# Alternar consonante/vocal produce algo pronunciable ("Bafo") en vez de ruido ("Xkqz").
_CONSONANTES = "bcdfghjklmnpqrstvwxyz"
_VOCALES = "aeiou"

# Orden por especificidad: fecha+hora completa de ECG debe ganarle a "sólo la fecha".
_PATRON_TOKEN_VALOR = re.compile(
    r"(?P<fecha_hora_ecg>\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})"
    r"|(?P<fecha_guion>\d{2}-[A-Za-z]{3}-\d{4})"
    r"|(?P<fecha_barra>\d{2}/\d{2}/\d{4})"
    r"|(?P<hora>\d{2}:\d{2}(?::\d{2})?)"
    r"|(?P<letras>[^\W\d_]+)"
    r"|(?P<digitos>\d+)",
    re.UNICODE,
)
_PATRON_FECHA_Y_HORA_ECG = re.compile(r"^(\d{2}-[A-Za-z]{3}-\d{4})(\s+)(\d{2}:\d{2}:\d{2})$")

# Protección adicional a ALLOWLIST_ESTRUCTURAL, sólo para el fixture parseable: vocabulario
# cerrado (secciones, medidas, sufijo "yr") que cada parser necesita encontrar literal para
# reconciliar el documento pero que la allowlist derivada de FIRMAS/_CAMPOS_HEADER no cubre.
_ETIQUETAS_SECCION_ECO: tuple[str, ...] = (
    "MEDIDAS",
    "MOTILIDAD SEGMENTARIA",
    "VALVULAS CARDIACAS",
    "AURICULAS",
    "PERICARDIO",
    "EVALUACION DE FLUJOS POR DOPPLER",
    "CONCLUSIONES",
    "AORTICA",
    "MITRAL",
    "PULMONAR",
    "TRICUSPIDEA",
    "IZQUIERDA",
    "DERECHA",
    "FLUJO AORTICO",
    "FLUJO MITRAL",
    "FLUJO PULMONAR",
    "FLUJO TRICUSPIDEO",
    # Valores cualitativos que la tabla de medidas usa en vez de un número (ver eco_doppler.py).
    "NORMAL",
    "VARIABLE",
)
_PATRON_ETIQUETAS_SECCION_ECO = _compilar_patron_allowlist(_ETIQUETAS_SECCION_ECO)
_PATRON_MATRICULA_ECO = re.compile(r"Matr[ií]cula\s+([A-Za-z])\s*(\d+)", re.IGNORECASE)

_ETIQUETAS_MEDIDA_ECG: tuple[str, ...] = ("yr", "PR interval", "QRS duration", "QT/QTc")
_PATRON_ETIQUETAS_MEDIDA_ECG = _compilar_patron_allowlist(_ETIQUETAS_MEDIDA_ECG)


def _spans_protegidos_adicionales(pagina: str, tipo_detectado: TipoDocumento) -> list[tuple[int, int]]:
    if tipo_detectado is TipoDocumento.LABORATORIO:
        return _spans_de_etiquetas(
            pagina,
            {
                "numero_peticion": _CAMPOS_HEADER_LAB["numero_peticion"],
                "medico_derivante": _CAMPOS_HEADER_LAB["medico_derivante"],
                "hora_extraccion": _CAMPOS_HEADER_LAB["hora_extraccion"],
            },
        )
    if tipo_detectado is TipoDocumento.ECOCARDIOGRAMA:
        spans = _spans_de_etiquetas(
            pagina,
            {
                "numero_estudio": _CAMPOS_HEADER_ECO["numero_estudio"],
                "matricula": "(?i)" + _PATRON_MATRICULA_ECO.pattern,
            },
        )
        spans.extend((m.start(), m.end()) for m in _PATRON_ETIQUETAS_SECCION_ECO.finditer(pagina))
        return spans
    if tipo_detectado is TipoDocumento.ECG:
        return [(m.start(), m.end()) for m in _PATRON_ETIQUETAS_MEDIDA_ECG.finditer(pagina)]
    return []


def _entero_deterministico(semilla: str, minimo: int, maximo: int) -> int:
    """Entero reproducible en `[minimo, maximo]`, función pura de `semilla` (hash, no posición)."""
    digest = hashlib.sha256(semilla.encode("utf-8")).digest()
    valor = int.from_bytes(digest[:8], "big")
    return minimo + valor % (maximo - minimo + 1)


def _sustituir_digitos(token: str) -> str:
    """Otro número de la misma cantidad de dígitos, reproducible por token."""
    digest = hashlib.sha256(f"digitos|{token}".encode()).digest()
    digitos = [str(digest[indice % len(digest)] % 10) for indice in range(len(token))]
    if token[0] != "0" and digitos[0] == "0":
        digitos[0] = str((digest[0] % 9) + 1)
    return "".join(digitos)


def _sustituir_letras(token: str) -> str:
    """Otra "palabra" de la misma longitud, alternando consonante/vocal, preservando mayús/minús."""
    digest = hashlib.sha256(f"letras|{token.lower()}".encode()).digest()
    fase_vocal = digest[0] % 2
    letras: list[str] = []
    for indice, original in enumerate(token):
        es_vocal = (indice + fase_vocal) % 2 == 1
        alfabeto = _VOCALES if es_vocal else _CONSONANTES
        letra = alfabeto[digest[(indice + 1) % len(digest)] % len(alfabeto)]
        letras.append(letra.upper() if original.isupper() else letra)
    return "".join(letras)


def _fecha_sintetica(semilla: str) -> date:
    """Fecha válida reproducible; día acotado a 1-28 para evitar límites de mes/año bisiesto."""
    dia = 1 + _entero_deterministico(f"dia|{semilla}", 0, 27)
    mes = 1 + _entero_deterministico(f"mes|{semilla}", 0, 11)
    anio = _entero_deterministico(f"anio|{semilla}", 2015, 2025)
    return date(anio, mes, dia)


def _hora_sintetica(semilla: str) -> tuple[int, int, int]:
    hora = _entero_deterministico(f"hora|{semilla}", 0, 23)
    minuto = _entero_deterministico(f"minuto|{semilla}", 0, 59)
    segundo = _entero_deterministico(f"segundo|{semilla}", 0, 59)
    return hora, minuto, segundo


def _edad_sintetica(semilla: str) -> int:
    return _entero_deterministico(f"edad|{semilla}", 1, 90)


def _formatear_fecha_barra(fecha: date) -> str:
    return fecha.strftime("%d/%m/%Y")


def _formatear_fecha_guion(fecha: date) -> str:
    return f"{fecha.day:02d}-{_MESES_INGLES_ABREVIADOS[fecha.month - 1]}-{fecha.year}"


def _formatear_hora(hora: int, minuto: int, segundo: int | None) -> str:
    if segundo is None:
        return f"{hora:02d}:{minuto:02d}"
    return f"{hora:02d}:{minuto:02d}:{segundo:02d}"


def _tiene_segundos(texto_hora: str) -> bool:
    return texto_hora.count(":") == 2


def _sustituto_fecha_hora_independiente(original: str, grupo: str | None) -> str:
    """Sustituto válido para fecha/hora sin coherencia clínica con otras fechas del documento."""
    if grupo == "fecha_hora_ecg":
        coincidencia = _PATRON_FECHA_Y_HORA_ECG.match(original)
        assert coincidencia is not None  # garantizado por el grupo que matcheó
        espacio = coincidencia.group(2)
        fecha_str = _formatear_fecha_guion(_fecha_sintetica(original))
        hora_h, hora_m, hora_s = _hora_sintetica(original)
        return f"{fecha_str}{espacio}{_formatear_hora(hora_h, hora_m, hora_s)}"
    if grupo == "fecha_guion":
        return _formatear_fecha_guion(_fecha_sintetica(original))
    if grupo == "fecha_barra":
        return _formatear_fecha_barra(_fecha_sintetica(original))
    hora_h, hora_m, hora_s = _hora_sintetica(original)
    return _formatear_hora(hora_h, hora_m, hora_s if _tiene_segundos(original) else None)


def _reemplazar_token_valor(coincidencia: re.Match[str], mapa_fechas_horas: dict[str, str]) -> str:
    """El mapa de coherencia se consulta primero, sin importar qué grupo matcheó (cubre la edad)."""
    original = coincidencia.group()
    grupo = coincidencia.lastgroup
    sustituto_coherente = mapa_fechas_horas.get(original)
    if sustituto_coherente is not None:
        return sustituto_coherente
    if grupo in ("fecha_hora_ecg", "fecha_guion", "fecha_barra", "hora"):
        return _sustituto_fecha_hora_independiente(original, grupo)
    if grupo == "letras":
        return _sustituir_letras(original)
    return _sustituir_digitos(original)  # grupo == "digitos"


def _sustituir_valores_en_segmento(segmento: str, mapa_fechas_horas: dict[str, str]) -> str:
    return _PATRON_TOKEN_VALOR.sub(lambda m: _reemplazar_token_valor(m, mapa_fechas_horas), segmento)


def _primer_segmento_valor(texto: str) -> str:
    """Mismo criterio que `_primer_segmento` de los tres parsers: trunca en 2+ espacios."""
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _campos_fecha_lab(texto: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave in ("fecha_nac", "fecha", "edad", "hora_extraccion"):
        coincidencia = re.search(_CAMPOS_HEADER_LAB[clave], texto)
        if coincidencia is not None:
            campos[clave] = _primer_segmento_valor(coincidencia.group(1))
    return campos


def _campos_fecha_eco(texto: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave in ("fecha", "edad"):
        coincidencia = re.search(_CAMPOS_HEADER_ECO[clave], texto)
        if coincidencia is not None:
            campos[clave] = _primer_segmento_valor(coincidencia.group(1))
    return campos


def _campos_fecha_ecg(texto: str) -> dict[str, str]:
    """No trunca en 2+ espacios como lab/eco: cortaría la hora del layout `DD-MON-YYYY␣␣HH:MM:SS`."""
    campos: dict[str, str] = {}
    for clave in ("fecha", "fecha_nac", "edad"):
        coincidencia = re.search(_CAMPOS_HEADER_ECG[clave], texto)
        if coincidencia is not None:
            campos[clave] = coincidencia.group(1).strip()
    return campos


def _mapa_fechas_horas_lab(texto: str) -> dict[str, str]:
    campos = _campos_fecha_lab(texto)
    mapa: dict[str, str] = {}
    fecha_estudio: date | None = None
    if "fecha" in campos:
        fecha_estudio = _fecha_sintetica(campos["fecha"])
        mapa[campos["fecha"]] = _formatear_fecha_barra(fecha_estudio)
    if fecha_estudio is not None and "fecha_nac" in campos:
        edad = _edad_sintetica(campos.get("edad", campos["fecha_nac"]))
        nacimiento = fecha_estudio.replace(year=fecha_estudio.year - edad)
        mapa[campos["fecha_nac"]] = _formatear_fecha_barra(nacimiento)
        if "edad" in campos:
            mapa[campos["edad"]] = str(edad)
    if "hora_extraccion" in campos:
        hora_h, hora_m, hora_s = _hora_sintetica(campos["hora_extraccion"])
        mapa[campos["hora_extraccion"]] = _formatear_hora(
            hora_h, hora_m, hora_s if _tiene_segundos(campos["hora_extraccion"]) else None
        )
    return mapa


def _mapa_fechas_horas_eco(texto: str) -> dict[str, str]:
    """El eco no trae fecha de nacimiento en el header: la edad queda como dígito genérico."""
    campos = _campos_fecha_eco(texto)
    if "fecha" not in campos:
        return {}
    return {campos["fecha"]: _formatear_fecha_barra(_fecha_sintetica(campos["fecha"]))}


def _mapa_fechas_horas_ecg(texto: str) -> dict[str, str]:
    campos = _campos_fecha_ecg(texto)
    mapa: dict[str, str] = {}
    fecha_estudio: date | None = None
    if "fecha" in campos:
        coincidencia = _PATRON_FECHA_Y_HORA_ECG.match(campos["fecha"])
        if coincidencia is not None:
            fecha_estudio = _fecha_sintetica(campos["fecha"])
            hora_h, hora_m, hora_s = _hora_sintetica(campos["fecha"])
            mapa[campos["fecha"]] = (
                f"{_formatear_fecha_guion(fecha_estudio)}{coincidencia.group(2)}"
                f"{_formatear_hora(hora_h, hora_m, hora_s)}"
            )
    if fecha_estudio is not None and "fecha_nac" in campos:
        edad = _edad_sintetica(campos.get("edad", campos["fecha_nac"]))
        nacimiento = fecha_estudio.replace(year=fecha_estudio.year - edad)
        mapa[campos["fecha_nac"]] = _formatear_fecha_guion(nacimiento)
        if "edad" in campos:
            mapa[campos["edad"]] = str(edad)
    return mapa


def _construir_mapa_fechas_horas(tipo_detectado: TipoDocumento, texto: TextoExtraido) -> dict[str, str]:
    """Mapa `fecha/hora original -> sustituto sintético coherente`, una vez por documento."""
    if tipo_detectado is TipoDocumento.LABORATORIO:
        return _mapa_fechas_horas_lab(texto.texto_completo_ordenado)
    if tipo_detectado is TipoDocumento.ECOCARDIOGRAMA:
        return _mapa_fechas_horas_eco(texto.texto_completo_ordenado)
    if tipo_detectado is TipoDocumento.ECG:
        return _mapa_fechas_horas_ecg(texto.texto_completo)
    return {}


def _spans_de_etiquetas(pagina: str, etiquetas: dict[str, str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for patron in etiquetas.values():
        coincidencia = re.search(patron, pagina)
        if coincidencia is not None and coincidencia.start() < coincidencia.start(1):
            spans.append((coincidencia.start(), coincidencia.start(1)))
    return spans


def _fusionar_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Colapsa spans solapados/adyacentes en su unión (evita descartar un span más grande)."""
    if not spans:
        return []
    ordenados = sorted(spans)
    fusionados = [ordenados[0]]
    for inicio, fin in ordenados[1:]:
        ultimo_inicio, ultimo_fin = fusionados[-1]
        if inicio <= ultimo_fin:
            fusionados[-1] = (ultimo_inicio, max(ultimo_fin, fin))
        else:
            fusionados.append((inicio, fin))
    return fusionados


def sustituir_por_valores_plausibles(
    texto: str, mapa_fechas_horas: dict[str, str], tipo_detectado: TipoDocumento
) -> str:
    """Igual que `enmascarar_por_forma`, pero sustituye por contenido sintético plausible.
    Además protege las etiquetas que el parser real necesita literalmente (`_spans_protegidos_adicionales`)."""
    spans = [(coincidencia.start(), coincidencia.end()) for coincidencia in _PATRON_ALLOWLIST.finditer(texto)]
    spans.extend(_spans_protegidos_adicionales(texto, tipo_detectado))
    spans = _fusionar_spans(spans)

    piezas: list[str] = []
    posicion = 0
    for inicio, fin in spans:
        piezas.append(_sustituir_valores_en_segmento(texto[posicion:inicio], mapa_fechas_horas))
        piezas.append(texto[inicio:fin])
        posicion = fin
    piezas.append(_sustituir_valores_en_segmento(texto[posicion:], mapa_fechas_horas))
    return "".join(piezas)


@dataclass(frozen=True)
class FixtureParseable:
    """Resultado de `generar_fixture_parseable`: mismo layout real, valores sintéticos plausibles."""

    tipo_detectado: TipoDocumento
    paginas: tuple[str, ...]
    paginas_ordenadas: tuple[str, ...]

    def formatear(self) -> str:
        """Mismo formato serializado que `Esqueleto.formatear()`, para reusar el mismo lector."""
        lineas = [
            "# fixture parseable -- generado con `anonimizacion esqueleto --modo parseable`",
            f"# tipo_detectado: {self.tipo_detectado.value}",
            "# ADVERTENCIA: todos los valores son SINTETICOS -- ninguno es un dato real de paciente.",
            "",
        ]
        for numero, pagina in enumerate(self.paginas, start=1):
            lineas.append(f"## pagina {numero} (orden de dibujado)")
            lineas.append(pagina)
        for numero, pagina in enumerate(self.paginas_ordenadas, start=1):
            lineas.append(f"## pagina {numero} (orden geometrico)")
            lineas.append(pagina)
        return "\n".join(lineas)


def generar_fixture_parseable(texto: TextoExtraido) -> FixtureParseable:
    """Genera un fixture parseable: mismo layout que `generar_esqueleto`, valores sintéticos."""
    tipo_detectado = detectar_tipo(texto)
    mapa_fechas_horas = _construir_mapa_fechas_horas(tipo_detectado, texto)
    return FixtureParseable(
        tipo_detectado=tipo_detectado,
        paginas=tuple(
            sustituir_por_valores_plausibles(pagina, mapa_fechas_horas, tipo_detectado) for pagina in texto.paginas
        ),
        paginas_ordenadas=tuple(
            sustituir_por_valores_plausibles(pagina, mapa_fechas_horas, tipo_detectado)
            for pagina in texto.paginas_ordenadas
        ),
    )
