"""Repositorio SQL para recuperar corridas y documentos luego de una interrupción."""

from __future__ import annotations

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.estados_corrida import EstadoDocumentoCorrida
from anonimizacion.salida.modelos_orm import CorridaOrm, DocumentoCorridaOrm

_ESTADOS_TERMINALES = {
    EstadoDocumentoCorrida.APROBADO,
    EstadoDocumentoCorrida.CUARENTENA,
    EstadoDocumentoCorrida.ERROR_FINAL,
}


class RepositorioCorridas:
    """Persiste la unidad administrativa y permite reanudar documentos no terminales."""

    def __init__(self, motor: Engine) -> None:
        self._motor = motor

    def crear_corrida(self, corrida: Corrida) -> None:
        with Session(self._motor) as sesion, sesion.begin():
            if sesion.get(CorridaOrm, corrida.id_corrida) is None:
                sesion.add(
                    CorridaOrm(
                        id_corrida=corrida.id_corrida,
                        estado=corrida.estado.value,
                        version=corrida.version,
                    )
                )

    def registrar_documento(self, documento: DocumentoCorrida) -> bool:
        with Session(self._motor) as sesion, sesion.begin():
            existente = sesion.scalar(
                select(DocumentoCorridaOrm.id).where(
                    DocumentoCorridaOrm.corrida_id == documento.corrida_id,
                    DocumentoCorridaOrm.huella_contenido == documento.huella_contenido,
                )
            )
            if existente is not None:
                return False
            sesion.add(
                DocumentoCorridaOrm(
                    corrida_id=documento.corrida_id,
                    huella_contenido=documento.huella_contenido,
                    ruta_autorizada=documento.ruta_autorizada,
                    estado=documento.estado.value,
                    version=documento.version,
                )
            )
            return True

    def documentos_para_reanudar(self, id_corrida: str) -> list[DocumentoCorrida]:
        with Session(self._motor) as sesion:
            filas = sesion.scalars(
                select(DocumentoCorridaOrm)
                .where(DocumentoCorridaOrm.corrida_id == id_corrida)
                .order_by(DocumentoCorridaOrm.id)
            ).all()
        return [
            self._a_documento(fila)
            for fila in filas
            if EstadoDocumentoCorrida(fila.estado) not in _ESTADOS_TERMINALES
        ]

    def actualizar_documento(self, documento: DocumentoCorrida, *, version_esperada: int) -> bool:
        """Confirma un estado sólo si ningún worker lo modificó desde la versión esperada."""
        with Session(self._motor) as sesion, sesion.begin():
            resultado = sesion.execute(
                update(DocumentoCorridaOrm)
                .where(
                    DocumentoCorridaOrm.corrida_id == documento.corrida_id,
                    DocumentoCorridaOrm.huella_contenido == documento.huella_contenido,
                    DocumentoCorridaOrm.version == version_esperada,
                )
                .values(estado=documento.estado.value, version=documento.version)
            )
            return resultado.rowcount == 1

    @staticmethod
    def _a_documento(fila: DocumentoCorridaOrm) -> DocumentoCorrida:
        return DocumentoCorrida(
            corrida_id=fila.corrida_id,
            huella_contenido=fila.huella_contenido,
            ruta_autorizada=fila.ruta_autorizada,
            estado=EstadoDocumentoCorrida(fila.estado),
            version=fila.version,
        )
