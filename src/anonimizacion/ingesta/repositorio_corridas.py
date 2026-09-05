"""Repositorio SQL para recuperar corridas y documentos luego de una interrupción."""

from __future__ import annotations

from collections.abc import Sequence

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

    def registrar_documentos(self, documentos: Sequence[DocumentoCorrida], *, tamano_lote: int = 1000) -> int:
        """Inventaría `documentos` en lotes -- una sesión por lote, no una por documento.

        Motivo medido (design.md, Decisión 5): `registrar_documento` abre una
        `Session` y una transacción por documento; 100.000 transacciones
        sueltas son minutos de arranque para un trabajo que en una sesión por
        millar son segundos. `registrar_documento` se conserva sin cambios --
        esta es la versión por lote, con la misma guarda de idempotencia por
        `(corrida_id, huella_contenido)` que `uq_documento_corrida_huella` ya
        exige: consulta las huellas existentes del lote antes de insertar, así
        que relanzar la misma corrida (mismo inventario, mismas huellas) no
        duplica el denominador del embudo.

        Devuelve la cantidad de filas efectivamente insertadas.
        """
        insertados = 0
        for inicio in range(0, len(documentos), tamano_lote):
            lote = documentos[inicio : inicio + tamano_lote]
            if not lote:
                continue
            with Session(self._motor) as sesion, sesion.begin():
                existentes = set(
                    sesion.execute(
                        select(DocumentoCorridaOrm.corrida_id, DocumentoCorridaOrm.huella_contenido).where(
                            DocumentoCorridaOrm.corrida_id.in_({d.corrida_id for d in lote}),
                            DocumentoCorridaOrm.huella_contenido.in_({d.huella_contenido for d in lote}),
                        )
                    ).all()
                )
                for documento in lote:
                    if (documento.corrida_id, documento.huella_contenido) in existentes:
                        continue
                    sesion.add(
                        DocumentoCorridaOrm(
                            corrida_id=documento.corrida_id,
                            huella_contenido=documento.huella_contenido,
                            ruta_autorizada=documento.ruta_autorizada,
                            estado=documento.estado.value,
                            version=documento.version,
                        )
                    )
                    insertados += 1
        return insertados

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
