"""Payloads tipados de `RegistroAnonimizado.contenido`, uno por `TipoDocumento`: punto medio
entre el `contenido` crudo de `parseo/` y las tablas SQL. Acá ya no hay PII de identidad
(reemplazada por HMAC `id_medico*`), pero el pivote a columnas fijas es responsabilidad de
`destinos/postgres.py`, no de este módulo."""

from __future__ import annotations

from dataclasses import dataclass

from ..dominio.senal_ecg import SenalEcg


@dataclass(frozen=True)
class FilaResultadoLaboratorio:
    """Una fila EAV de laboratorio, ya lista para `resultado_laboratorio` (analito/seccion/valor/unidad/rango)."""

    analito: str
    seccion: str
    valor_num: float | None
    valor_texto: str | None
    unidad: str | None
    ref_min: float | None
    ref_max: float | None


@dataclass(frozen=True)
class ContenidoLaboratorioSalida:
    """Payload de salida de un laboratorio: médico pseudonimizado + resultados EAV."""

    id_medico: str | None
    resultados: tuple[FilaResultadoLaboratorio, ...]


@dataclass(frozen=True)
class ContenidoEcgSalida:
    """Payload de salida de un ECG: médico pseudonimizado + medidas. `senal` se propaga tal
    cual (ni PII ni pivote, geometría medida); `None` cuando el layout no validó."""

    id_medico: str | None
    vent_rate: str | None
    pr_interval: str | None
    qrs_duration: str | None
    qt_qtc: str | None
    ejes: str | None
    senal: SenalEcg | None = None


@dataclass(frozen=True)
class FilaMedidaEco:
    """Una medida estructurada del eco tal como la entrega el parser (nombre/valor/unidad), sin pivotear todavía."""

    nombre: str
    valor: str
    unidad: str | None


@dataclass(frozen=True)
class FilaTextoSeccionEco:
    """Texto libre de una sección del eco (ya depurado de PII por la etapa de detección de PII, Fase 5/8)."""

    nombre: str
    texto: str


@dataclass(frozen=True)
class ContenidoEcoSalida:
    """Payload de salida de un eco: médicos pseudonimizados + medidas + texto libre por sección."""

    id_medico_solicitante: str | None
    id_medico_informante: str | None
    id_matricula_informante: str | None
    medidas: tuple[FilaMedidaEco, ...]
    secciones_texto: tuple[FilaTextoSeccionEco, ...]
