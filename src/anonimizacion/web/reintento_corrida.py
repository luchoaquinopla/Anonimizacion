"""Modelo de lectura del plan de reintento de una corrida (feature `reanudacion-de-corridas`).

`POST /corridas/{id}/reintentar` (`web/rutas_corridas.py`) sólo debe reencolar
los documentos apartados con código **reintentable** de esa corrida -- los
determinísticos no se tocan: reprocesarlos sin cambios produce el mismo
fallo, y quema CPU real para llegar al mismo resultado. La única definición de
qué código es reintentable vive en `dominio.errores.es_reintentable`; este
módulo NUNCA duplica esa lista, sólo la consulta.

Separación de responsabilidades, mismo corte que `embudo_corrida.py`: este
módulo LEE y arma el plan (qué reencolar, qué se descarta y por qué), nunca
despacha nada -- eso lo hace `web/servicio_corridas.py::ServicioCorridasReal.reintentar_corrida`,
reusando el mismo camino de despacho que `crear_corrida` (`_despachar_y_cerrar`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from anonimizacion.dominio.errores import CodigoErrorDocumento, es_reintentable
from anonimizacion.salida.modelos_orm import CorridaOrm, Cuarentena, DocumentoCorridaOrm

# Forma exacta que exige el centinela de claves de `trabajadores.tareas.procesar_grupo`
# (design.md de `panel-de-operacion`, Decisión 1): nunca una cuarta clave.
ReferenciaDocumento = Mapping[str, str]


@dataclass(frozen=True)
class PlanDeReintento:
    """Resultado de clasificar los apartados de una corrida.

    `ruta_autorizada` puede ser `None` para corridas creadas antes de la
    migración `0011` (sin backfill) -- si `reintentables` no está vacío en
    ese caso, `ServicioCorridasReal.reintentar_corrida` no puede reencolar
    nada y lo señala como error, no como cero silencioso.
    """

    corrida_id: str
    ruta_autorizada: str | None
    reintentables: tuple[ReferenciaDocumento, ...]
    descartados_por_codigo: Mapping[str, int] = field(default_factory=dict)

    @property
    def total_descartados(self) -> int:
        return sum(self.descartados_por_codigo.values())


def construir_plan_reintento(motor: Engine, id_corrida: str) -> PlanDeReintento | None:
    """`None` si `id_corrida` no existe -- el llamador lo traduce a un error explícito.

    Dos consultas agregadas, ninguna trae más filas de las estrictamente
    necesarias para decidir: primero `(id_documento, codigo)` de `cuarentena`
    para clasificar; recién si hay al menos un reintentable, una segunda
    consulta a `documento_corrida` para reconstruir la `uri` original de
    ESOS documentos (nunca se lee `ruta_autorizada` de los descartados: no
    hace falta, y es justo el campo que puede llevar PII de carpeta).
    """
    with Session(motor) as sesion:
        corrida = sesion.get(CorridaOrm, id_corrida)
        if corrida is None:
            return None

        filas = sesion.execute(
            select(Cuarentena.id_documento, Cuarentena.codigo).where(Cuarentena.corrida_id == id_corrida)
        ).all()

        ids_reintentables: list[str] = []
        descartados_por_codigo: dict[str, int] = {}
        for id_documento, codigo in filas:
            if es_reintentable(CodigoErrorDocumento(codigo)):
                ids_reintentables.append(id_documento)
            else:
                descartados_por_codigo[codigo] = descartados_por_codigo.get(codigo, 0) + 1

        referencias: tuple[ReferenciaDocumento, ...] = ()
        if ids_reintentables:
            filas_documento = sesion.execute(
                select(DocumentoCorridaOrm.huella_contenido, DocumentoCorridaOrm.ruta_autorizada).where(
                    DocumentoCorridaOrm.corrida_id == id_corrida,
                    DocumentoCorridaOrm.huella_contenido.in_(ids_reintentables),
                )
            ).all()
            uri_por_huella = dict(filas_documento)
            faltantes = [huella for huella in ids_reintentables if huella not in uri_por_huella]
            if faltantes:
                # No debería pasar nunca en operación normal: todo código
                # reintentable ocurre DESPUÉS del inventario (ver el
                # docstring del módulo `ingesta/lanzador_corrida.py` sobre
                # cuándo se persiste `documento_corrida`), así que para
                # cuando la corrida llega a un estado terminal el inventario
                # ya está completo. Si esto se dispara, es corrupción real
                # (una fila de `documento_corrida` borrada, o un `id_documento`
                # de cuarentena que nunca vino de esta corrida) -- fallar
                # ruidoso en vez de reintentar con una `uri` inventada.
                raise RuntimeError(
                    f"reintentar_corrida: {len(faltantes)} documento(s) reintentable(s) de "
                    f"{id_corrida} no tienen fila en documento_corrida -- no se puede "
                    "reconstruir su uri para reprocesarlos (inventario incompleto o corrupción)"
                )
            referencias = tuple(
                {"id_documento": huella, "uri": uri_por_huella[huella], "sha256": huella}
                for huella in ids_reintentables
            )

    return PlanDeReintento(
        corrida_id=id_corrida,
        ruta_autorizada=corrida.ruta_autorizada,
        reintentables=referencias,
        descartados_por_codigo=descartados_por_codigo,
    )
