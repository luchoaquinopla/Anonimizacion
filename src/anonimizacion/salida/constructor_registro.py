"""Ensamblaje final: `DocumentoParseado` + `ClavesPaciente` -> `RegistroAnonimizado` (tasks.md 7.2).

Última parada antes de cualquier destino de escritura (`destinos/postgres.py`,
`destinos/parquet.py`). Responsabilidades de `construir_registro`:

1. Reemplazar `id_paciente`/`id_alt_paciente` crudos por los ya resueltos en
   `ClavesPaciente` (Fase 6) y adjuntar `id_episodio` (ya resuelto por
   `pseudonimizacion/vinculacion.py`, Fase 6 -- se recibe como parámetro
   porque `vinculacion.py` opera en batch sobre todo el lote, no documento a
   documento, así que no puede ir dentro de `ClavesPaciente`, que sí es
   por-documento).
2. Pseudonimizar al médico (decisión Q3): nombre -> `id_medico`
   (`pseudonimizacion.claves.generar_id_medico`), matrícula ->
   `id_matricula_medico` (`generar_id_matricula_medico`) cuando el documento
   trae firma. El nombre/matrícula crudos NUNCA llegan a `RegistroAnonimizado`
   -- ni en `contenido` ni en `adicionales`.
3. Tipar `contenido` según `modelos_salida.py` (uno por `TipoDocumento`).

4. Redactar PII de texto libre (`ContenidoEco.secciones_texto`) -- fix
   aditivo de PR9 que cierra un gap dejado explícitamente abierto por PR7/PR8
   (ver `apply-progress` de esas sesiones y el docstring de
   `pii/redaccion.py`): `pii/politica.py::clasificar` ya detecta PII en texto
   libre desde PR4, pero nadie usaba esos hallazgos para redactar antes de
   este ensamblaje. Ahora `construir_registro` recibe un `motor_pii`
   opcional (mismo patrón "modo degradado" que `observabilidad/
   bitacora_segura.py`: sin motor solo se redactan DNIs por regex; con motor
   -- el que inyecta `pipeline/ejecutor.py`, ya cargado -- también se
   redactan nombres/otras entidades vía NER) y aplica
   `pii/redaccion.py::redactar_texto` sobre cada sección de texto libre
   antes de armar `ContenidoEcoSalida.secciones_texto`.

Tampoco decide el pivote ancho de `MedidaEco` a columnas fijas de
`medicion_eco` -- eso es una decisión de la capa SQL, no del ensamblado de
dominio (ver `destinos/postgres.py`).
"""

from __future__ import annotations

from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pii.redaccion import DetectorEntidades, redactar_texto
from anonimizacion.pseudonimizacion.claves import generar_id_matricula_medico, generar_id_medico
from anonimizacion.salida.modelos_salida import (
    ContenidoEcgSalida,
    ContenidoEcoSalida,
    ContenidoLaboratorioSalida,
    FilaMedidaEco,
    FilaResultadoLaboratorio,
    FilaTextoSeccionEco,
)

_CLAVE_MEDICO_DERIVANTE = "medico_derivante"
_CLAVE_MEDICO_SOLICITANTE = "medico_solicitante"
_CLAVES_PERSONAL = (_CLAVE_MEDICO_DERIVANTE, _CLAVE_MEDICO_SOLICITANTE, "tecnico")


def _pseudonimizar_medico_de_adicionales(
    adicionales: dict, pepper: bytes, clave: str
) -> str | None:
    """Extrae `adicionales[clave]` (nombre crudo del médico) y devuelve su `id_medico`, si está."""
    nombre = adicionales.get(clave)
    if not nombre:
        return None
    return generar_id_medico(pepper, str(nombre))


def _adicionales_sin_personal(adicionales: dict) -> dict:
    return {clave: valor for clave, valor in adicionales.items() if clave not in _CLAVES_PERSONAL}


def _parsear_float(texto: str) -> float | None:
    try:
        return float(texto.strip().replace(",", "."))
    except ValueError:
        return None


def _parsear_rango_referencia(texto: str | None) -> tuple[float | None, float | None]:
    """Parsea rangos `"min-max"` (p.ej. `"12-16"`); cualquier otro formato queda `(None, None)`.

    El layout de columnas real todavía no está calibrado contra el corpus
    (ver `parseo/laboratorio_general.py`, mismo comentario) -- este parser
    tolerante evita que un formato de rango inesperado tumbe todo el
    registro; simplemente no completa `ref_min`/`ref_max` para esa fila.
    """
    if texto is None:
        return None, None
    partes = texto.split("-")
    if len(partes) != 2:
        return None, None
    minimo = _parsear_float(partes[0])
    maximo = _parsear_float(partes[1])
    return minimo, maximo


def _contenido_laboratorio_salida(documento: DocumentoParseado, id_medico: str | None) -> ContenidoLaboratorioSalida:
    filas: list[FilaResultadoLaboratorio] = []
    for resultado in documento.contenido.resultados:
        valor_num = _parsear_float(resultado.resultado)
        ref_min, ref_max = _parsear_rango_referencia(resultado.valores_referencia)
        filas.append(
            FilaResultadoLaboratorio(
                analito=resultado.prueba,
                seccion=resultado.seccion,
                valor_num=valor_num,
                valor_texto=None if valor_num is not None else resultado.resultado,
                unidad=resultado.unidades,
                ref_min=ref_min,
                ref_max=ref_max,
            )
        )
    return ContenidoLaboratorioSalida(id_medico=id_medico, resultados=tuple(filas))


def _contenido_ecg_salida(documento: DocumentoParseado, id_medico: str | None) -> ContenidoEcgSalida:
    contenido = documento.contenido
    return ContenidoEcgSalida(
        id_medico=id_medico,
        vent_rate=contenido.vent_rate,
        pr_interval=contenido.pr_interval,
        qrs_duration=contenido.qrs_duration,
        qt_qtc=contenido.qt_qtc,
        ejes=contenido.ejes,
    )


def _contenido_eco_salida(
    documento: DocumentoParseado,
    pepper: bytes,
    id_medico_solicitante: str | None,
    motor_pii: DetectorEntidades | None,
) -> ContenidoEcoSalida:
    contenido = documento.contenido
    firma = contenido.firma

    id_medico_informante = generar_id_medico(pepper, firma.nombre) if firma is not None else None
    id_matricula_informante = (
        generar_id_matricula_medico(pepper, firma.matricula) if firma is not None else None
    )

    medidas = tuple(
        FilaMedidaEco(nombre=medida.nombre, valor=medida.valor, unidad=medida.unidad)
        for medida in contenido.medidas
    )
    # Fix aditivo PR9 (cierra gap PR7/PR8): texto libre dictado puede traer
    # PII incidental (ver docstring del módulo y `pii/redaccion.py`).
    secciones_texto = tuple(
        FilaTextoSeccionEco(
            nombre=seccion.nombre, texto=redactar_texto(seccion.texto, motor_pii=motor_pii)
        )
        for seccion in contenido.secciones_texto
    )

    return ContenidoEcoSalida(
        id_medico_solicitante=id_medico_solicitante,
        id_medico_informante=id_medico_informante,
        id_matricula_informante=id_matricula_informante,
        medidas=medidas,
        secciones_texto=secciones_texto,
    )


def construir_registro(
    documento: DocumentoParseado,
    claves: ClavesPaciente,
    *,
    id_episodio: str,
    pepper: bytes,
    motor_pii: DetectorEntidades | None = None,
) -> RegistroAnonimizado:
    """Ensambla el `RegistroAnonimizado` final: cero PII, `contenido` tipado por `TipoDocumento`."""
    if claves.id_paciente is None:
        raise ValueError("ClavesPaciente.id_paciente no resuelto -- construir_registro requiere una clave válida")

    adicionales = dict(documento.adicionales)

    if documento.tipo_documento is TipoDocumento.LABORATORIO:
        id_medico = _pseudonimizar_medico_de_adicionales(adicionales, pepper, _CLAVE_MEDICO_DERIVANTE)
        contenido = _contenido_laboratorio_salida(documento, id_medico)
    elif documento.tipo_documento is TipoDocumento.ECG:
        id_medico = _pseudonimizar_medico_de_adicionales(adicionales, pepper, _CLAVE_MEDICO_DERIVANTE)
        contenido = _contenido_ecg_salida(documento, id_medico)
    elif documento.tipo_documento is TipoDocumento.ECOCARDIOGRAMA:
        id_medico_solicitante = _pseudonimizar_medico_de_adicionales(
            adicionales, pepper, _CLAVE_MEDICO_SOLICITANTE
        )
        contenido = _contenido_eco_salida(documento, pepper, id_medico_solicitante, motor_pii)
    else:
        raise ValueError(f"tipo_documento no soportado por construir_registro: {documento.tipo_documento!r}")

    return RegistroAnonimizado(
        id_paciente=claves.id_paciente,
        id_episodio=id_episodio,
        tipo_documento=documento.tipo_documento,
        version_esquema=documento.version_esquema,
        fecha_estudio=documento.fecha_estudio,
        # Se propagan tal cual, sin transformar (Requirement: "Hora local sin
        # conversión de huso" / "Ausencia explícita cuando el documento no
        # trae hora", spec `momento-del-estudio`).
        hora_estudio=documento.hora_estudio,
        precision_hora=documento.precision_hora,
        contenido=contenido,
        adicionales=_adicionales_sin_personal(adicionales),
    )
