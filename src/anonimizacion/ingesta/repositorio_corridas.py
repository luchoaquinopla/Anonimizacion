"""Repositorio SQL para recuperar corridas y documentos luego de una interrupción.
`documentos_para_reanudar`/`actualizar_documento` sin llamador de producción todavía."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from anonimizacion.dominio.corridas import Corrida, DocumentoCorrida
from anonimizacion.dominio.estados_corrida import EstadoCorrida, EstadoDocumentoCorrida
from anonimizacion.salida.modelos_orm import CorridaOrm, Cuarentena, DocumentoCorridaOrm, Estudio

_ESTADOS_TERMINALES = {
    EstadoDocumentoCorrida.APROBADO,
    EstadoDocumentoCorrida.CUARENTENA,
    EstadoDocumentoCorrida.ERROR_FINAL,
}

# Estados terminales de `corrida` (plano de control, distinto de `_ESTADOS_TERMINALES`).
_ESTADOS_CORRIDA_TERMINALES = {
    EstadoCorrida.COMPLETADA,
    EstadoCorrida.COMPLETADA_CON_CUARENTENA,
    EstadoCorrida.FALLIDA,
}


def _es_activa(estado: EstadoCorrida) -> bool:
    """`CorridaOrm.activa`: el gate de "una corrida a la vez" vive en la base, no en un lock."""
    return estado not in _ESTADOS_CORRIDA_TERMINALES


class RepositorioCorridas:
    """Persiste la unidad administrativa y permite reanudar documentos no terminales."""

    def __init__(self, motor: Engine) -> None:
        self._motor = motor

    def crear_corrida(self, corrida: Corrida) -> None:
        """Inserta la fila o deja que la base la rechace (`ux_corrida_una_activa`) sin atrapar."""
        with Session(self._motor) as sesion, sesion.begin():
            if sesion.get(CorridaOrm, corrida.id_corrida) is None:
                sesion.add(
                    CorridaOrm(
                        id_corrida=corrida.id_corrida,
                        estado=corrida.estado.value,
                        version=corrida.version,
                        activa=_es_activa(corrida.estado),
                        ruta_autorizada=corrida.ruta_autorizada,
                    )
                )

    def obtener_corrida(self, id_corrida: str) -> Corrida | None:
        """Recupera `Corrida` (estado + version) para volver a avanzarla."""
        with Session(self._motor) as sesion:
            fila = sesion.get(CorridaOrm, id_corrida)
        if fila is None:
            return None
        return Corrida(
            id_corrida=fila.id_corrida,
            estado=EstadoCorrida(fila.estado),
            version=fila.version,
            ruta_autorizada=fila.ruta_autorizada,
        )

    def listar_corridas_no_terminales(self) -> list[Corrida]:
        """Corridas en cualquier estado activo; orden estable por `id_corrida` para el gate 409."""
        with Session(self._motor) as sesion:
            filas = sesion.scalars(
                select(CorridaOrm)
                .where(CorridaOrm.estado.not_in({e.value for e in _ESTADOS_CORRIDA_TERMINALES}))
                .order_by(CorridaOrm.id_corrida)
            ).all()
        return [
            Corrida(id_corrida=fila.id_corrida, estado=EstadoCorrida(fila.estado), version=fila.version)
            for fila in filas
        ]

    def ultima_actividad(self, id_corrida: str) -> datetime | None:
        """Máximo entre `corrida.actualizada_en`, último `estudio` y última `cuarentena`.
        Limitación conocida: el inventario no tiene columna de tiempo propia."""
        with Session(self._motor) as sesion:
            fila = sesion.get(CorridaOrm, id_corrida)
            if fila is None:
                return None
            ultimo_estudio = sesion.scalar(
                select(func.max(Estudio.creado_en)).where(Estudio.corrida_id == id_corrida)
            )
            ultima_cuarentena = sesion.scalar(
                select(func.max(Cuarentena.creado_en)).where(Cuarentena.corrida_id == id_corrida)
            )
        candidatos = [fila.actualizada_en, ultimo_estudio, ultima_cuarentena]
        return max(momento for momento in candidatos if momento is not None)

    def registrar_latido(self, id_corrida: str) -> None:
        """Toca sólo `corrida.actualizada_en`, sin bloqueo optimista ni transición de dominio.
        Cubre la ventana larga de un corpus plano donde `listar_grupos` no entrega nada aún."""
        with Session(self._motor) as sesion, sesion.begin():
            sesion.execute(
                update(CorridaOrm)
                .where(CorridaOrm.id_corrida == id_corrida)
                .values(actualizada_en=datetime.now(timezone.utc))
            )

    def registrar_documentos(self, documentos: Sequence[DocumentoCorrida], *, tamano_lote: int = 1000) -> int:
        """Inventaría `documentos` en lotes, una sesión por lote, idempotente por huella.
        Devuelve la cantidad de filas efectivamente insertadas."""
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

    def actualizar_corrida(self, corrida: Corrida, *, version_esperada: int) -> bool:
        """Persiste `corrida.estado`, mismo bloqueo optimista que `actualizar_documento`."""
        with Session(self._motor) as sesion, sesion.begin():
            resultado = sesion.execute(
                update(CorridaOrm)
                .where(
                    CorridaOrm.id_corrida == corrida.id_corrida,
                    CorridaOrm.version == version_esperada,
                )
                .values(estado=corrida.estado.value, version=corrida.version, activa=_es_activa(corrida.estado))
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
