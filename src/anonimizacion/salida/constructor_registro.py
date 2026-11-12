"""Ensamblaje final: `DocumentoParseado` + `ClavesPaciente` -> `RegistroAnonimizado`, última
parada antes de escribir a Postgres. Pseudonimiza al médico (nombre/matrícula crudos NUNCA
llegan a `RegistroAnonimizado`); redacta PII de texto libre en tres capas (regex DNI, nombres
YA CONOCIDOS de este documento por comparación exacta -- sin depender del NER --, y NER si se
inyecta `motor_pii`); propaga `clave_documento`/`campos_no_extraidos` tal cual, sin recalcularlos."""

from __future__ import annotations

from typing import Callable

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


def _nombres_conocidos_documento(documento: DocumentoParseado) -> tuple[str, ...]:
    """Nombres YA CONOCIDOS de este documento (paciente + médico), por duck typing sobre
    `contenido.firma`; se usan para redactar por comparación exacta, no para pseudonimizar."""
    nombres = [documento.identidad.nombre.get_secret_value()]
    medico_solicitante = documento.adicionales.get(_CLAVE_MEDICO_SOLICITANTE)
    if medico_solicitante:
        nombres.append(str(medico_solicitante))
    firma = getattr(documento.contenido, "firma", None)
    nombre_firma = getattr(firma, "nombre", None) if firma is not None else None
    if nombre_firma:
        nombres.append(nombre_firma)
    return tuple(nombres)


def _parsear_float(texto: str) -> float | None:
    try:
        return float(texto.strip().replace(",", "."))
    except ValueError:
        return None


def _parsear_rango_referencia(texto: str | None) -> tuple[float | None, float | None]:
    """Parsea rangos `"min-max"`; cualquier otro formato queda `(None, None)` en vez de tumbar
    el registro entero."""
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
        senal=contenido.senal,
    )


def _contenido_eco_salida(
    documento: DocumentoParseado,
    pepper: bytes,
    id_medico_solicitante: str | None,
    motor_pii: DetectorEntidades | None,
    nombres_conocidos: tuple[str, ...],
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
    # Texto libre dictado puede traer PII incidental: además del regex de DNI y el NER, se compara contra nombres_conocidos de este documento.
    secciones_texto = tuple(
        FilaTextoSeccionEco(
            nombre=seccion.nombre,
            texto=redactar_texto(
                seccion.texto, motor_pii=motor_pii, nombres_conocidos=nombres_conocidos
            ),
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


def _construir_contenido_laboratorio(
    documento: DocumentoParseado, adicionales: dict, pepper: bytes, motor_pii: DetectorEntidades | None
) -> ContenidoLaboratorioSalida:
    id_medico = _pseudonimizar_medico_de_adicionales(adicionales, pepper, _CLAVE_MEDICO_DERIVANTE)
    return _contenido_laboratorio_salida(documento, id_medico)


def _construir_contenido_ecg(
    documento: DocumentoParseado, adicionales: dict, pepper: bytes, motor_pii: DetectorEntidades | None
) -> ContenidoEcgSalida:
    id_medico = _pseudonimizar_medico_de_adicionales(adicionales, pepper, _CLAVE_MEDICO_DERIVANTE)
    return _contenido_ecg_salida(documento, id_medico)


def _construir_contenido_eco(
    documento: DocumentoParseado, adicionales: dict, pepper: bytes, motor_pii: DetectorEntidades | None
) -> ContenidoEcoSalida:
    id_medico_solicitante = _pseudonimizar_medico_de_adicionales(adicionales, pepper, _CLAVE_MEDICO_SOLICITANTE)
    nombres_conocidos = _nombres_conocidos_documento(documento)
    return _contenido_eco_salida(documento, pepper, id_medico_solicitante, motor_pii, nombres_conocidos)


# Registry por tipo, mismo idioma que parseo/registro.py; preserva ValueError si el tipo falta, no KeyError crudo.
_CONSTRUCTORES_POR_TIPO: dict[
    TipoDocumento, Callable[[DocumentoParseado, dict, bytes, "DetectorEntidades | None"], object]
] = {
    TipoDocumento.LABORATORIO: _construir_contenido_laboratorio,
    TipoDocumento.ECG: _construir_contenido_ecg,
    TipoDocumento.ECOCARDIOGRAMA: _construir_contenido_eco,
}


def construir_registro(
    documento: DocumentoParseado,
    claves: ClavesPaciente,
    *,
    id_episodio: str,
    pepper: bytes,
    clave_documento: str,
    motor_pii: DetectorEntidades | None = None,
    campos_no_extraidos: tuple[str, ...] = (),
) -> RegistroAnonimizado:
    """Ensambla el `RegistroAnonimizado` final: cero PII, `contenido` tipado por `TipoDocumento`."""
    if claves.id_paciente is None:
        raise ValueError("ClavesPaciente.id_paciente no resuelto -- construir_registro requiere una clave válida")

    adicionales = dict(documento.adicionales)

    constructor = _CONSTRUCTORES_POR_TIPO.get(documento.tipo_documento)
    if constructor is None:
        raise ValueError(f"tipo_documento no soportado por construir_registro: {documento.tipo_documento!r}")
    contenido = constructor(documento, adicionales, pepper, motor_pii)

    return RegistroAnonimizado(
        id_paciente=claves.id_paciente,
        id_episodio=id_episodio,
        tipo_documento=documento.tipo_documento,
        version_esquema=documento.version_esquema,
        fecha_estudio=documento.fecha_estudio,
        # Hora local sin conversión de huso; ausencia explícita si el documento no trae hora.
        hora_estudio=documento.hora_estudio,
        precision_hora=documento.precision_hora,
        contenido=contenido,
        adicionales=_adicionales_sin_personal(adicionales),
        clave_documento=clave_documento,
        campos_no_extraidos=campos_no_extraidos,
    )
