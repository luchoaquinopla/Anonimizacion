"""Máquina de transiciones de corrida y documento -- ver `estados_corrida.py`
para por qué existe, qué le falta para conectarse a producción y qué
decisión lo desbloquea.
"""

from __future__ import annotations

from dataclasses import dataclass

from .estados_corrida import EstadoCorrida, EstadoDocumentoCorrida

# `CREADA -> FALLIDA` y `PROCESANDO -> {COMPLETADA, COMPLETADA_CON_CUARENTENA,
# FALLIDA}` directas (feature `despachador-desde-el-panel`):
#
# - `CREADA -> FALLIDA`: recuperación de arranque
#   (`lanzador_corrida.recuperar_corridas_abandonadas`). El servidor es de UN
#   SOLO proceso, sin persistencia de "hay un hilo corriendo para este
#   corrida_id" -- si el proceso muere entre `crear_corrida` (fila insertada
#   en CREADA) y el primer `avanzar_a(INVENTARIANDO)`, esa fila queda
#   abandonada en CREADA para siempre sin esta transición.
# - `PROCESANDO -> {COMPLETADA, COMPLETADA_CON_CUARENTENA}` DIRECTA (sin pasar
#   por RECONCILIANDO/PUBLICANDO): en esta arquitectura,
#   `trabajadores.tareas.procesar_grupo` ya reconcilia y publica CADA grupo de
#   punta a punta en una sola llamada síncrona (Fase 2.5,
#   `operacion-segura-y-escalable`) -- no hay ningún paso administrativo
#   separado de "reconciliando" ni "publicando" que el despachador real
#   atraviese. Forzarlo a pasar por esos estados para cerrar la corrida
#   inventariaría una fase que nadie ejecuta -- la misma clase de mentira que
#   `fix/silencios-de-ingesta-y-panel` ya cerró en la punta de arranque
#   (`PROCESANDO` sin que nada procese). RECONCILIANDO/PUBLICANDO se
#   conservan para un futuro despachador que sí separe esas fases; no se
#   eliminan, sólo dejan de ser el único camino hacia un cierre.
_TRANSICIONES_CORRIDA = {
    EstadoCorrida.CREADA: {EstadoCorrida.INVENTARIANDO, EstadoCorrida.FALLIDA},
    EstadoCorrida.INVENTARIANDO: {EstadoCorrida.PROCESANDO, EstadoCorrida.FALLIDA},
    EstadoCorrida.PROCESANDO: {
        EstadoCorrida.RECONCILIANDO,
        EstadoCorrida.COMPLETADA,
        EstadoCorrida.COMPLETADA_CON_CUARENTENA,
        EstadoCorrida.FALLIDA,
    },
    EstadoCorrida.RECONCILIANDO: {EstadoCorrida.PUBLICANDO, EstadoCorrida.COMPLETADA_CON_CUARENTENA, EstadoCorrida.FALLIDA},
    EstadoCorrida.PUBLICANDO: {EstadoCorrida.COMPLETADA, EstadoCorrida.COMPLETADA_CON_CUARENTENA, EstadoCorrida.FALLIDA},
    # `FALLIDA`/`COMPLETADA_CON_CUARENTENA` -> `PROCESANDO` (feature
    # `reanudacion-de-corridas`): la ÚNICA salida de un estado terminal en
    # todo este mapa, y a propósito angosta. `ServicioCorridasReal.reintentar_corrida`
    # es la única escritora de esta transición -- reencola sólo los apartados
    # con código reintentable (`dominio/errores.py::es_reintentable`) bajo el
    # MISMO `corrida_id`, nunca crea una corrida nueva. `COMPLETADA` (cero
    # apartados) deliberadamente NO tiene salida: no hay nada que reintentar,
    # y agregar la transición ahí sería ofrecer un botón sin ningún camino
    # real detrás -- misma lógica que `_GRUPO_ES_UNIDAD_COMPLETA` en
    # `pipeline/ejecutor.py` (no exponer una perilla sin la contabilidad
    # detrás).
    EstadoCorrida.COMPLETADA: set(),
    EstadoCorrida.COMPLETADA_CON_CUARENTENA: {EstadoCorrida.PROCESANDO},
    EstadoCorrida.FALLIDA: {EstadoCorrida.PROCESANDO},
}

_TRANSICIONES_DOCUMENTO = {
    EstadoDocumentoCorrida.INVENTARIADO: {EstadoDocumentoCorrida.CLASIFICADO, EstadoDocumentoCorrida.ERROR_FINAL},
    EstadoDocumentoCorrida.CLASIFICADO: {EstadoDocumentoCorrida.EXTRAIDO_MINIMO, EstadoDocumentoCorrida.ERROR_FINAL},
    EstadoDocumentoCorrida.EXTRAIDO_MINIMO: {EstadoDocumentoCorrida.ASOCIADO, EstadoDocumentoCorrida.ERROR_RECUPERABLE, EstadoDocumentoCorrida.ERROR_FINAL},
    EstadoDocumentoCorrida.ASOCIADO: {EstadoDocumentoCorrida.EXTRAIDO_COMPLETO, EstadoDocumentoCorrida.CUARENTENA},
    EstadoDocumentoCorrida.EXTRAIDO_COMPLETO: {EstadoDocumentoCorrida.RECONCILIADO, EstadoDocumentoCorrida.CUARENTENA},
    EstadoDocumentoCorrida.RECONCILIADO: {EstadoDocumentoCorrida.APROBADO, EstadoDocumentoCorrida.CUARENTENA},
    EstadoDocumentoCorrida.ERROR_RECUPERABLE: {EstadoDocumentoCorrida.CLASIFICADO, EstadoDocumentoCorrida.ERROR_FINAL},
    EstadoDocumentoCorrida.APROBADO: set(),
    EstadoDocumentoCorrida.CUARENTENA: set(),
    EstadoDocumentoCorrida.ERROR_FINAL: set(),
}


@dataclass
class DocumentoCorrida:
    corrida_id: str
    huella_contenido: str
    ruta_autorizada: str
    estado: EstadoDocumentoCorrida = EstadoDocumentoCorrida.INVENTARIADO
    version: int = 0

    @classmethod
    def inventariado(cls, *, corrida_id: str, huella_contenido: str, ruta_autorizada: str) -> DocumentoCorrida:
        return cls(corrida_id=corrida_id, huella_contenido=huella_contenido, ruta_autorizada=ruta_autorizada)

    def avanzar_a(self, destino: EstadoDocumentoCorrida) -> None:
        if destino not in _TRANSICIONES_DOCUMENTO[self.estado]:
            raise ValueError(f"transicion de documento invalida: {self.estado.value} -> {destino.value}")
        self.estado = destino
        self.version += 1

    def reanudar_desde(self) -> EstadoDocumentoCorrida:
        return self.estado


@dataclass
class Corrida:
    id_corrida: str
    estado: EstadoCorrida = EstadoCorrida.CREADA
    version: int = 0
    # Raíz autorizada que se inventarió para esta corrida (feature
    # `reanudacion-de-corridas`). Campo opcional al final, mismo precedente
    # que `clave_documento`/`corrida_id` en otros dataclasses: nace `None`
    # para no romper fixtures ni llamadores existentes. Sin esto, un
    # reintento no tiene forma de reconstruir la raíz autorizada que
    # `trabajadores.despacho_paralelo.inicializar_trabajador` exige (`entrada`)
    # para volver a validar que cada documento sigue dentro de una raíz
    # permitida -- ver `web/reintento_corrida.py`.
    ruta_autorizada: str | None = None

    @classmethod
    def crear(cls, id_corrida: str, *, ruta_autorizada: str | None = None) -> Corrida:
        return cls(id_corrida=id_corrida, ruta_autorizada=ruta_autorizada)

    def avanzar_a(self, destino: EstadoCorrida) -> None:
        if destino not in _TRANSICIONES_CORRIDA[self.estado]:
            raise ValueError(f"transicion de corrida invalida: {self.estado.value} -> {destino.value}")
        self.estado = destino
        self.version += 1
