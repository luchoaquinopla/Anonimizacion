"""Parser de laboratorio general (spec `document-parsing`).

Los PDFs reales son multipágina con el header repetido en cada página y las
secciones de resultados (HEMATOLOGIA, HEMOSTASIA, QUÍMICA CLÍNICA, IONOGRAMA)
repartidas entre ellas. El parser reconcilia todas las páginas en un único
`DocumentoParseado` por Nº de Petición: toma el header de la primera página
que lo trae completo, valida que el Nº de Petición no cambie entre páginas
(si cambia, son dos estudios mezclados por error de escaneo/orden — falla
explícito en vez de mezclar resultados de dos pacientes) y concatena las
filas de resultado de TODAS las páginas en un único `ContenidoLaboratorio`.

Nota de formato: el layout real de columnas (Resultado Actual/Unidades/
Valores de Referencia) todavía no está calibrado contra el corpus real (ver
design.md, "Pendientes"). Estos parsers asumen un separador `|` explícito
por fila de resultado como formato de trabajo estable y sin ambigüedad de
espacios; se recalibra contra PDFs reales sin cambiar la forma pública del
parser (misma entrada `TextoExtraido`, misma salida `DocumentoParseado`).

Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección "Fix:
extracción con sort=True + firmas ECG reales"): este parser lee
`texto.paginas_ordenadas` (orden geométrico, `sort=True`), no `texto.paginas`
(orden de dibujado) -- el PDF real dibuja etiquetas y valores en pasadas
separadas del content stream, y solo el orden geométrico los deja adyacentes
como espera el regex "Etiqueta: valor". Como dos campos pueden compartir la
misma fila visual (columna izquierda + columna derecha, p. ej. "Apellido y
Nombre: X      Fecha: Y" en una sola línea), cada campo capturado se trunca
en el primer separador de 2+ espacios (`_primer_segmento`, misma convención
que `parseo/ecg_mortara.py`) para no arrastrar el campo siguiente como parte
del valor.

Fix post-PR9 #4 (recalibración lab/eco contra 3 documentos reales, ver
`sdd/pdf-pii-anonymization/apply-progress`): calibrado contra un único
documento real de laboratorio, tres variantes de etiqueta no contempladas
por los regex anteriores: `F.Nacimiento :` (espacio antes de los dos
puntos), `Médico:` (sin la palabra "derivante") y `Hora de Extracción:`
(con "de" en el medio). `_CAMPOS_HEADER` se ajustó para tolerar espacio
opcional antes de `:` y palabras intermedias opcionales, sin dejar de
matchear las variantes originales (los cambios son estrictamente más
permisivos, backward compatible). Calibrado contra una sola muestra —
podría no generalizar a otras variantes de formato no vistas.

Fix post-PR9 #6 (cuerpo real de resultados, ver
`sdd/pdf-pii-anonymization/apply-progress`): el fix #4 solo calibró el
HEADER contra el documento real; el CUERPO (filas de resultado) seguía
asumiendo el formato `|` sintético y nunca matcheaba nada contra un
documento real (0 filas extraídas). `_extraer_resultados` ahora reconoce
también el formato real: columnas separadas por 2+ espacios (`\\s{2,}`,
misma convención que `_primer_segmento`), fila válida cuando el segundo
token tiene forma numérica (entero o decimal, con signo opcional) — el
resto de columnas (unidad / rango de referencia) se clasifican por forma:
un token con forma `"min - max"` es rango, cualquier otro token no-rango es
unidad. El formato `|` legado se preserva sin cambios para no romper las
fixtures sintéticas existentes (se intenta primero). Además:
- La sección puede aparecer en dos formas en el mismo documento real
  (`-NOMBRE-` con guiones en línea propia, seguido inmediatamente de
  `NOMBRE` sin guiones como aparente duplicado) — ambas se normalizan
  (guiones + acentos removidos) antes de comparar contra `_SECCIONES`.
- Hay sub-bloques dentro de una sección conocida (p. ej. "HEMOGRAMA" dentro
  de "HEMATOLOGIA") que el modelo `ResultadoLaboratorio` no distingue de la
  sección padre (campo `seccion` plano) — se usa el nombre de
  sección/sub-bloque MÁS RECIENTE visto como `seccion` de cada fila
  siguiente. Heurística de detección de sub-bloque (`_es_subencabezado_seccion`):
  línea sin dígitos, sin `:`, íntegramente en mayúsculas y solo
  letras/espacios/puntos — filtra la enorme mayoría del ruido real (notas
  metodológicas, párrafos legales, líneas de firma, que vienen en
  minúsculas o mixto), pero podría no generalizar a un sub-encabezado real
  con dígitos o símbolos no vistos en la muestra calibrada.
- Ruido explícito filtrado sin romper el parseo: encabezado de columna
  repetido por página (`_es_encabezado_tabla_repetido`, detecta "RESULTADO"
  + "UNIDADES"/"REFERENCIA" en la misma línea), número de página, notas con
  `:`.

Fix post-merge (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
"Fix: persistencia del puente id_alt_paciente en Postgres entre corridas"):
resuelve el gap anterior de "nombre de prueba partido en dos líneas" (p. ej.
`"Filtrado Glomerular Estimado (CKD-EPI    102 ... mL/min/1.73m²"` seguido
de una línea de continuación `" 2021)"`). `_extraer_resultados` ahora recorre
las líneas por índice (no con un `for` simple) para poder mirar la línea
SIGUIENTE cuando reconoce una fila válida: si la columna de nombre
(`tokens[0]`) trae un paréntesis sin cerrar (`_completar_nombre_partido`), y
la línea siguiente (a) NO es en sí misma otra fila válida (no tiene un
segundo token numérico tras separar por 2+ espacios, `_es_linea_continuacion_de_nombre`)
y (b) al concatenarla balancea los paréntesis, se fusiona como el resto del
nombre y esa línea se consume (no se vuelve a procesar como ruido). Si no se
cumplen esas condiciones, el nombre queda como estaba (sin forzar una fusión
insegura) — heurística deliberadamente conservadora: solo actúa cuando hay
un paréntesis desbalanceado de por medio, así que no puede afectar ninguna
fila de una sola línea (la gran mayoría) que no tenga ese patrón. Calibrado
contra una sola muestra real — igual que el resto de heurísticas de este
módulo, podría no generalizar a una variante de formato no vista.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import SecretStr

from anonimizacion.dominio.errores import CodigoErrorDocumento, ErrorParseo
from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.extraccion.texto_pymupdf import TextoExtraido

_ETAPA = "parseo"
_VERSION_ESQUEMA = 1

_SECCIONES = ("HEMATOLOGIA", "HEMOSTASIA", "QUIMICA CLINICA", "IONOGRAMA")

_PATRON_VALOR_FILA = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_PATRON_RANGO_REFERENCIA = re.compile(r"^[+-]?\d+(?:[.,]\d+)?\s*-\s*[+-]?\d+(?:[.,]\d+)?$")

_MAPA_ACENTOS = str.maketrans("ÁÉÍÓÚáéíóúÜüÀÈÌÒÙàèìòù", "AEIOUaeiouUuAEIOUaeiou")

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
    """Trunca en el primer salto de 2+ espacios (separador de columnas del reporte).

    Con `sort=True`, dos campos que comparten la misma fila visual (columna
    izquierda + columna derecha) pueden quedar en la misma línea del texto
    extraído; 2+ espacios es el separador que el propio documento usa para
    alinearlas. Misma convención que `parseo/ecg_mortara.py::_primer_segmento`.
    """
    return re.split(r"\s{2,}", texto, maxsplit=1)[0].strip()


def _extraer_campos_header(pagina: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    for clave, patron in _CAMPOS_HEADER.items():
        coincidencia = re.search(patron, pagina)
        if coincidencia:
            campos[clave] = _primer_segmento(coincidencia.group(1))
    return campos


def _parsear_fecha(texto: str) -> date:
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def _parsear_fecha_nacimiento(texto: str) -> str | None:
    """Normaliza `F.Nacimiento` a ISO 8601 (`YYYY-MM-DD`).

    Fix post-PR9 (ver `sdd/pdf-pii-anonymization/apply-progress`, sección
    "Fix: recalibración parser ECG contra layout real Mortara"): el puente
    `id_alt_paciente -> id_paciente` (`pseudonimizacion/claves.py`,
    `generar_id_alt_paciente`) usa el string de fecha de nacimiento tal cual
    dentro del mensaje HMAC. El laboratorio trae `DD/MM/YYYY` pero el ECG
    (`parseo/ecg_mortara.py`) trae `DD-MON-YYYY` — sin normalizar ambos a la
    misma representación canónica, el mismo paciente real produciría dos
    `id_alt_paciente` distintos y el puente nunca resolvería. Si no se puede
    parsear, se descarta (no participa del puente) en vez de propagar un
    formato crudo inconsistente.
    """
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _quitar_acentos(texto: str) -> str:
    return texto.translate(_MAPA_ACENTOS)


def _normalizar_encabezado_seccion(linea_limpia: str) -> str:
    """Normaliza una línea candidata a nombre de sección: quita acentos,
    guiones (el documento real trae `-NOMBRE-`) y mayusculiza, para poder
    compararla contra `_SECCIONES` sin importar la variante exacta."""
    return _quitar_acentos(linea_limpia).strip().strip("-").strip().upper()


def _es_encabezado_tabla_repetido(candidata: str) -> bool:
    """Encabezado de columnas repetido en cada página del documento real
    (`"Pruebas   Resultado   ...   Unidades   Valores de Referencia"`) —
    ruido a ignorar, no un nombre de sección ni una fila de resultado."""
    return "RESULTADO" in candidata and ("UNIDADES" in candidata or "REFERENCIA" in candidata)


def _es_subencabezado_seccion(linea_limpia: str, candidata: str) -> bool:
    """Heurística para sub-bloques dentro de una sección conocida (ver
    docstring del módulo, Fix post-PR9 #6): línea sin dígitos, sin `:`,
    íntegramente en mayúsculas y compuesta solo de letras/espacios/puntos.
    Filtra la enorme mayoría del ruido real (notas, párrafos legales,
    firmas), que viene en minúsculas o mixto — podría no generalizar a un
    sub-encabezado con dígitos o símbolos no vistos en la muestra."""
    if ":" in linea_limpia or any(caracter.isdigit() for caracter in linea_limpia):
        return False
    if linea_limpia != linea_limpia.upper():
        return False
    return bool(re.fullmatch(r"[A-Z\s.]+", candidata))


def _clasificar_columnas_extra(tokens: list[str]) -> tuple[str | None, str | None]:
    """Clasifica las columnas después de nombre+valor: un token con forma
    `"min - max"` es rango de referencia, cualquier otro es unidad (se
    conserva el primero no-rango encontrado)."""
    unidades: str | None = None
    valores_referencia: str | None = None
    for token in tokens:
        if _PATRON_RANGO_REFERENCIA.match(token):
            valores_referencia = token
        elif unidades is None:
            unidades = token
    return unidades, valores_referencia


def _es_linea_continuacion_de_nombre(linea_limpia: str) -> bool:
    """True si `linea_limpia` es candidata a ser el CIERRE de un nombre de
    prueba partido en dos líneas: trae un paréntesis de cierre y NO es, en sí
    misma, otra fila válida (no tiene un segundo token numérico tras separar
    por 2+ espacios) -- evita confundir la línea siguiente REAL de una fila
    con el cierre de un nombre partido."""
    if ")" not in linea_limpia:
        return False
    tokens = [token for token in re.split(r"\s{2,}", linea_limpia) if token]
    return not (len(tokens) >= 2 and _PATRON_VALOR_FILA.match(tokens[1]))


def _completar_nombre_partido(nombre_prueba: str, lineas: list[str], indice: int) -> tuple[str, int]:
    """Reconstruye un nombre de prueba partido en dos líneas por un paréntesis sin cerrar.

    Si `nombre_prueba` (la columna de nombre de la fila en `lineas[indice]`)
    trae un paréntesis SIN cerrar y la línea siguiente lo balancea, devuelve
    `(nombre_completo, 1)` -- el `1` le indica al llamador que consuma esa
    línea siguiente en vez de procesarla de nuevo. Si no aplica el patrón
    (paréntesis ya balanceado, no hay línea siguiente, la siguiente es en sí
    misma otra fila, o concatenar no balancea los paréntesis), devuelve
    `(nombre_prueba, 0)` sin cambios -- deliberadamente conservador, prefiere
    dejar el nombre truncado (comportamiento anterior) antes que fusionar de
    forma insegura."""
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


def _extraer_resultados(pagina: str) -> tuple[ResultadoLaboratorio, ...]:
    resultados: list[ResultadoLaboratorio] = []
    seccion_actual: str | None = None
    lineas = pagina.splitlines()
    indice = 0
    while indice < len(lineas):
        linea_limpia = lineas[indice].strip()
        if not linea_limpia:
            indice += 1
            continue
        candidata = _normalizar_encabezado_seccion(linea_limpia)

        if _es_encabezado_tabla_repetido(candidata):
            indice += 1
            continue

        if candidata in _SECCIONES:
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
        if len(tokens) >= 2 and _PATRON_VALOR_FILA.match(tokens[1]):
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

    return tuple(resultados)


class ParseadorLaboratorioGeneral:
    """Parser del layout de laboratorio general; reconcilia header multi-página."""

    tipo_documento = TipoDocumento.LABORATORIO

    def parsear(self, texto: TextoExtraido) -> DocumentoParseado:
        header: dict[str, str] | None = None
        resultados: list[ResultadoLaboratorio] = []

        for pagina in texto.paginas_ordenadas:
            campos_pagina = _extraer_campos_header(pagina)
            numero_peticion_pagina = campos_pagina.get("numero_peticion")

            if numero_peticion_pagina:
                if header is None:
                    header = campos_pagina
                elif numero_peticion_pagina != header.get("numero_peticion"):
                    raise ErrorParseo(
                        codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA
                    )

            resultados.extend(_extraer_resultados(pagina))

        if header is None or "nombre" not in header or "fecha" not in header:
            raise ErrorParseo(codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA)

        try:
            fecha_estudio = _parsear_fecha(header["fecha"])
        except ValueError as _exc:
            raise ErrorParseo(
                codigo=CodigoErrorDocumento.PARSEO_INCOMPLETO, etapa=_ETAPA
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
            if clave not in ("nombre", "dni", "fecha_nac", "fecha", "numero_peticion")
        }

        contenido = ContenidoLaboratorio(
            numero_peticion=header.get("numero_peticion", ""),
            resultados=tuple(resultados),
        )

        return DocumentoParseado(
            tipo_documento=TipoDocumento.LABORATORIO,
            version_esquema=_VERSION_ESQUEMA,
            identidad=identidad,
            fecha_estudio=fecha_estudio,
            contenido=contenido,
            adicionales=adicionales,
        )
