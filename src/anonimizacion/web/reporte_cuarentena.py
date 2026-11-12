"""Modelo de lectura del reporte de cuarentena: traduce códigos internos a QUÉ HACER
(pedir material, revisar el programa, revisar a mano). No renderiza -- eso es
`plantilla_reporte.py`. Sin PII: `cuarentena` sólo guarda identificador técnico y metadatos."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.salida.modelos_orm import Cuarentena

from .codigos_cuarentena import EXPLICACION_POR_CODIGO, EXPLICACION_POR_DETALLE_PARSEO

_BYTES_POR_MIB = 1024 * 1024


class AccionRequerida(str, Enum):
    """Qué hay que hacer con un documento apartado, no por qué se apartó."""

    PEDIR_MATERIAL = "pedir_material"
    REVISAR_EL_PROGRAMA = "revisar_el_programa"
    REVISAR_A_MANO = "revisar_a_mano"
    # Un escaneo sin capa de texto no es un bug del parser, es material para OCR.
    NECESITA_OCR = "necesita_ocr"
    SIN_CLASIFICAR = "sin_clasificar"


#: Paleta de ESTADO fija: el color nunca viaja solo, siempre con etiqueta y símbolo.
@dataclass(frozen=True)
class PresentacionAccion:
    titulo: str
    que_significa: str
    que_hacer: str
    color: str
    simbolo: str


PRESENTACION: dict[AccionRequerida, PresentacionAccion] = {
    AccionRequerida.PEDIR_MATERIAL: PresentacionAccion(
        titulo="Falta material del paciente",
        que_significa="El grupo de estudios está incompleto o tiene estudios repetidos.",
        que_hacer="Pedir al instituto el estudio faltante y volver a procesar el grupo.",
        color="#fab219",
        simbolo="◐",
    ),
    AccionRequerida.REVISAR_EL_PROGRAMA: PresentacionAccion(
        titulo="El programa no pudo leerlo",
        que_significa="El documento llegó completo pero no se pudo extraer o verificar su contenido.",
        que_hacer="Avisar al equipo de desarrollo con el identificador del documento.",
        color="#ec835a",
        simbolo="▲",
    ),
    AccionRequerida.REVISAR_A_MANO: PresentacionAccion(
        titulo="Identidad sin resolver",
        que_significa="No se pudo determinar con certeza a qué paciente pertenece el estudio.",
        que_hacer="Revisar el caso a mano: reprocesar no lo corrige por sí solo.",
        color="#d03b3b",
        simbolo="■",
    ),
    AccionRequerida.NECESITA_OCR: PresentacionAccion(
        titulo="Escaneo sin texto, necesita OCR",
        que_significa="El documento es una imagen escaneada: no tiene una capa de texto nativa que se pueda extraer.",
        que_hacer="Pasar el documento por OCR (o pedir al instituto la versión con texto nativo) y volver a procesarlo.",
        color="#3b82c4",
        simbolo="▤",
    ),
    AccionRequerida.SIN_CLASIFICAR: PresentacionAccion(
        titulo="Sin clasificar",
        que_significa="Un motivo que todavía no está descrito en este reporte.",
        que_hacer="Avisar al equipo: el reporte quedó desactualizado respecto del programa.",
        color="#898781",
        simbolo="?",
    ),
}

_ACCION_POR_CODIGO: dict[str, AccionRequerida] = {
    # Nivel episodio: el documento está bien, el grupo no.
    "episodio_incompleto": AccionRequerida.PEDIR_MATERIAL,
    "episodio_ambiguo": AccionRequerida.PEDIR_MATERIAL,
    # Nivel documento: no se pudo leer, parsear o verificar.
    "tipo_no_reconocido": AccionRequerida.REVISAR_EL_PROGRAMA,
    "parseo_incompleto": AccionRequerida.REVISAR_EL_PROGRAMA,
    "evidencia_ausente": AccionRequerida.REVISAR_EL_PROGRAMA,
    "evidencia_ambigua": AccionRequerida.REVISAR_EL_PROGRAMA,
    "valor_discrepante": AccionRequerida.REVISAR_EL_PROGRAMA,
    "cobertura_incompleta": AccionRequerida.REVISAR_EL_PROGRAMA,
    "cobertura_ambigua": AccionRequerida.REVISAR_EL_PROGRAMA,
    "artefacto_sobretamano": AccionRequerida.REVISAR_EL_PROGRAMA,
    "error_transitorio_agotado": AccionRequerida.REVISAR_EL_PROGRAMA,
    "pdf_ilegible": AccionRequerida.REVISAR_EL_PROGRAMA,
    "sin_capa_de_texto": AccionRequerida.NECESITA_OCR,
    # Reprocesar sin cambios puede andar (murió el proceso, no el documento), pero un
    # patrón repetido es señal de infraestructura -- igual amerita avisar al equipo.
    "proceso_interrumpido": AccionRequerida.REVISAR_EL_PROGRAMA,
    # Identidad: reprocesar no lo arregla.
    "clave_pii_no_resuelta": AccionRequerida.REVISAR_A_MANO,
    "clave_pii_ambigua": AccionRequerida.REVISAR_A_MANO,
}

# Traducción compartida con plantilla_panel.py -- no se copia, se desincronizaría.
_EXPLICACION_POR_CODIGO = EXPLICACION_POR_CODIGO


@dataclass(frozen=True)
class DetalleCuarentena:
    """Una línea del reporte. Sin PII: `id_documento` es un identificador técnico."""

    id_documento: str
    tipo_documento: str | None
    codigo: str
    explicacion: str
    ubicacion: str | None


@dataclass(frozen=True)
class GrupoDeAccion:
    accion: AccionRequerida
    detalles: tuple[DetalleCuarentena, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.detalles)

    @property
    def presentacion(self) -> PresentacionAccion:
        return PRESENTACION[self.accion]


@dataclass(frozen=True)
class ReporteCuarentena:
    por_accion: dict[AccionRequerida, GrupoDeAccion]

    @property
    def total(self) -> int:
        return sum(grupo.total for grupo in self.por_accion.values())

    @property
    def grupos_con_casos(self) -> tuple[GrupoDeAccion, ...]:
        """Sólo los grupos que tienen algo. Una ficha en cero es ruido."""
        return tuple(grupo for grupo in self.por_accion.values() if grupo.total)


def _explicar(fila: Cuarentena) -> str:
    if fila.codigo == "artefacto_sobretamano":
        tamano = (fila.tamano_bytes or 0) / _BYTES_POR_MIB
        tope = (fila.tope_bytes or 0) / _BYTES_POR_MIB
        return f"El archivo pesa {tamano:.0f} MiB y el tope configurado es de {tope:.0f} MiB."
    if fila.detalle_parseo:
        # El detalle de qué faltó reemplaza el mensaje genérico de parseo_incompleto.
        return EXPLICACION_POR_DETALLE_PARSEO.get(
            fila.detalle_parseo, _EXPLICACION_POR_CODIGO.get(fila.codigo, "Motivo no descrito en este reporte.")
        )
    return _EXPLICACION_POR_CODIGO.get(fila.codigo, "Motivo no descrito en este reporte.")


def _ubicar(fila: Cuarentena) -> str | None:
    if fila.campo and fila.pagina is not None:
        return f"{fila.campo}, página {fila.pagina}"
    return fila.campo or None


def construir_reporte(motor: Engine) -> ReporteCuarentena:
    """Lee la cuarentena y la agrupa por la acción que requiere cada caso."""
    with Session(motor) as sesion:
        filas = sesion.scalars(sa.select(Cuarentena).order_by(Cuarentena.id)).all()

    acumulado: dict[AccionRequerida, list[DetalleCuarentena]] = {
        accion: [] for accion in AccionRequerida
    }
    for fila in filas:
        # Un código sin clasificar NO se descarta: aparece en su propio grupo.
        accion = _ACCION_POR_CODIGO.get(fila.codigo, AccionRequerida.SIN_CLASIFICAR)
        acumulado[accion].append(
            DetalleCuarentena(
                id_documento=fila.id_documento,
                tipo_documento=fila.tipo_documento,
                codigo=fila.codigo,
                explicacion=_explicar(fila),
                ubicacion=_ubicar(fila),
            )
        )

    return ReporteCuarentena(
        por_accion={
            accion: GrupoDeAccion(accion, tuple(detalles))
            for accion, detalles in acumulado.items()
        }
    )
