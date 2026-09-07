"""Modelo de lectura del reporte de cuarentena: agrupa por QUÉ HACER.

El médico que opera el pipeline no necesita saber qué significa
`cobertura_ambigua`. Necesita saber si tiene que pedirle un estudio al instituto,
avisarle al equipo de desarrollo, o revisar un caso a mano. Este módulo traduce
códigos internos a esas tres acciones.

Esa traducción sólo es posible desde que los motivos de nivel episodio dejaron de
compartir código con los de nivel campo (spec `procesamiento-por-grupo`): antes,
"a este paciente le falta el ecocardiograma" y "no pude verificar el potasio"
llegaban con el mismo nombre y la pregunta no tenía respuesta.

Este módulo NO renderiza: devuelve datos. La presentación vive en
`plantilla_reporte.py`, y así el agrupamiento se puede probar sin HTML de por
medio.

Privacidad: la tabla `cuarentena` no guarda PII por diseño --- sólo un
identificador técnico, la etapa, el código y metadatos de ubicación. Este módulo
no agrega nada que no esté ahí.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from anonimizacion.salida.modelos_orm import Cuarentena

from .codigos_cuarentena import EXPLICACION_POR_CODIGO

_BYTES_POR_MIB = 1024 * 1024


class AccionRequerida(str, Enum):
    """Qué hay que hacer con un documento apartado, no por qué se apartó."""

    PEDIR_MATERIAL = "pedir_material"
    REVISAR_EL_PROGRAMA = "revisar_el_programa"
    REVISAR_A_MANO = "revisar_a_mano"
    SIN_CLASIFICAR = "sin_clasificar"


#: Cómo se ve cada acción. Los colores son la paleta de ESTADO (fija, nunca
#: temática): en superficie clara `warning` y `serious` quedan por debajo de 3:1
#: a propósito, y la mitigación es que siempre viajan con etiqueta y símbolo ---
#: nunca color solo.
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
    # Distinto texto que "error_transitorio_agotado" (ver codigos_cuarentena.py),
    # misma acción: reprocesar sin cambios puede andar (el proceso murió, no
    # el documento), pero igual amerita avisar al equipo -- un patrón de
    # OOM-kill repetido es una señal de infraestructura, no algo para ignorar.
    "proceso_interrumpido": AccionRequerida.REVISAR_EL_PROGRAMA,
    # Identidad: reprocesar no lo arregla.
    "clave_pii_no_resuelta": AccionRequerida.REVISAR_A_MANO,
    "clave_pii_ambigua": AccionRequerida.REVISAR_A_MANO,
}

# La traducción de códigos a texto llano vive en `codigos_cuarentena.py` --
# `plantilla_panel.py` (Tramo 5) la comparte para la columna "Motivos" del
# embudo por etapa. No se copia acá: dos tablas iguales se desincronizan sin
# falta, y ahí tendríamos dos pantallas diciendo cosas distintas del mismo
# código de error.
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
        # Informa el tamaño real y el tope aplicado para que ajustar el límite
        # sea leer el reporte y no adivinar.
        tamano = (fila.tamano_bytes or 0) / _BYTES_POR_MIB
        tope = (fila.tope_bytes or 0) / _BYTES_POR_MIB
        return f"El archivo pesa {tamano:.0f} MiB y el tope configurado es de {tope:.0f} MiB."
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
        # Perderlo dejaría documentos apartados fuera de todos los totales, que
        # es exactamente la clase de silencio que este proyecto viene corrigiendo.
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
