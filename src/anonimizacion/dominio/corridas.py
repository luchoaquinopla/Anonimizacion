from __future__ import annotations

from dataclasses import dataclass

from .estados_corrida import EstadoCorrida, EstadoDocumentoCorrida

_TRANSICIONES_CORRIDA = {
    EstadoCorrida.CREADA: {EstadoCorrida.INVENTARIANDO},
    EstadoCorrida.INVENTARIANDO: {EstadoCorrida.PROCESANDO, EstadoCorrida.FALLIDA},
    EstadoCorrida.PROCESANDO: {EstadoCorrida.RECONCILIANDO, EstadoCorrida.FALLIDA},
    EstadoCorrida.RECONCILIANDO: {EstadoCorrida.PUBLICANDO, EstadoCorrida.COMPLETADA_CON_CUARENTENA, EstadoCorrida.FALLIDA},
    EstadoCorrida.PUBLICANDO: {EstadoCorrida.COMPLETADA, EstadoCorrida.COMPLETADA_CON_CUARENTENA, EstadoCorrida.FALLIDA},
    EstadoCorrida.COMPLETADA: set(),
    EstadoCorrida.COMPLETADA_CON_CUARENTENA: set(),
    EstadoCorrida.FALLIDA: set(),
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

    @classmethod
    def crear(cls, id_corrida: str) -> Corrida:
        return cls(id_corrida=id_corrida)

    def avanzar_a(self, destino: EstadoCorrida) -> None:
        if destino not in _TRANSICIONES_CORRIDA[self.estado]:
            raise ValueError(f"transicion de corrida invalida: {self.estado.value} -> {destino.value}")
        self.estado = destino
        self.version += 1
