"""Payloads tipados de `RegistroAnonimizado.contenido`, uno por `TipoDocumento` (tasks.md 7.2).

Estos dataclasses son el punto medio entre el `contenido` crudo de
`DocumentoParseado` (los `ContenidoEcg`/`ContenidoLaboratorio`/`ContenidoEco`
de `parseo/`) y las tablas SQL de `modelos_orm.py`: acá ya no queda PII de
identidad (nombre/DNI/fecha de nacimiento del médico quedan reemplazados por
sus HMAC `id_medico*`), pero la forma todavía es "genérica" -- no pivotea
`MedidaEco` a columnas fijas. Ese pivote (la decisión "ancha" del eco) es
responsabilidad de la capa de escritura SQL (`destinos/postgres.py`), no de
este módulo: acá se decide QUÉ es PII y se saca, ahí se decide CÓMO se
guarda en columnas.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    """Payload de salida de un ECG: médico pseudonimizado + medidas (esquema fijo)."""

    id_medico: str | None
    vent_rate: str | None
    pr_interval: str | None
    qrs_duration: str | None
    qt_qtc: str | None
    ejes: str | None


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
