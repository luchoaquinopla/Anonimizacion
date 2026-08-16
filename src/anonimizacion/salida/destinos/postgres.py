"""Escritor del destino Postgres (tasks.md 7.3, design.md decisión Q1: Postgres como sistema de registro).

`EscritorPostgres` recibe un `sqlalchemy.Engine` ya armado (inyección de
dependencia -- construir ese `Engine` con la URL real de Postgres es
responsabilidad de la configuración del pipeline, Fase 8/9, todavía no
implementada). En este repo, sin Postgres instalado, los tests lo instancian
con `sqlite:///:memory:` (ver `tests/salida/destinos/test_postgres.py` para
el porqué eso es válido acá).

`registrar_vinculo` respalda `ResolutorClaves` (Fase 6) contra la tabla real
`vinculo_paciente`, preservando la MISMA semántica de ambigüedad de
homónimos documentada en `pseudonimizacion/resolutor_claves.py` --
deliberadamente NO usa `INSERT ... ON CONFLICT (id_alt_paciente) DO UPDATE`:
ese patrón pisaría en silencio un puente en conflicto (el bug corregido
post-PR5, commit 07da933). En su lugar hace SELECT explícito y decide entre
INSERT / no-op / marcar ambiguo, calcado del método `registrar_puente` de
`ResolutorClaves`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from anonimizacion.dominio.modelos import RegistroAnonimizado
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.salida.modelos_orm import (
    Episodio,
    MedicionEco,
    MedicionEcg,
    ResultadoLaboratorio,
    TextoSeccionEco,
    VinculoPaciente,
)
from anonimizacion.salida.modelos_salida import ContenidoEcgSalida, ContenidoEcoSalida, ContenidoLaboratorioSalida

# Pivote de la decisión "ancha" para el eco (ver modelos_orm.py::MedicionEco):
# nombre tal como lo imprime el equipo (mayúsculas, normalizado por el
# parser) -> columna fija. Cualquier medida que no matchee acá cae a
# `adicionales` en vez de perderse (ver design.md, "Pendientes": el layout
# real de nombres de medida todavía no está calibrado contra el corpus).
_PIVOTE_MEDIDAS_ECO: dict[str, str] = {
    "AO": "ao",
    "AI": "ai",
    "DDVI": "ddvi",
    "DSVI": "dsvi",
    "FA": "fa",
    "SEPTUM": "septum",
    "P. POSTERIOR": "p_posterior",
    "P.POSTERIOR": "p_posterior",
}


class EscritorPostgres:
    """Escribe `RegistroAnonimizado` y vínculos de paciente contra el esquema de `modelos_orm.py`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # --- vinculo_paciente: respaldo persistente de ResolutorClaves ---------

    def registrar_vinculo(self, id_alt_paciente: str, id_paciente: str) -> None:
        with Session(self._engine) as sesion, sesion.begin():
            existente = sesion.get(VinculoPaciente, id_alt_paciente)

            if existente is None:
                sesion.add(VinculoPaciente(id_alt_paciente=id_alt_paciente, id_paciente=id_paciente, ambiguo=False))
                return

            if existente.ambiguo:
                return  # ya ambiguo -- permanece ambiguo, no hay vuelta atrás

            if existente.id_paciente == id_paciente:
                return  # reprocesamiento idempotente del mismo laboratorio

            # mismo id_alt_paciente, id_paciente distinto -> homónimos reales
            existente.id_paciente = None
            existente.ambiguo = True

    def resolver_vinculo(self, id_alt_paciente: str) -> str | None:
        with Session(self._engine) as sesion:
            fila = sesion.get(VinculoPaciente, id_alt_paciente)
            if fila is None or fila.ambiguo:
                return None
            return fila.id_paciente

    def es_ambiguo(self, id_alt_paciente: str) -> bool:
        with Session(self._engine) as sesion:
            fila = sesion.get(VinculoPaciente, id_alt_paciente)
            return fila is not None and fila.ambiguo

    # --- episodio: determinístico, sin riesgo de ambigüedad -----------------

    def escribir_episodio(self, *, id_episodio: str, id_paciente: str, fecha_ancla: date) -> None:
        """Idempotente: `id_episodio` es una función pura de `(id_paciente, fecha_ancla)`.

        A diferencia de `vinculo_paciente`, acá no hay riesgo de ambigüedad:
        el mismo `id_episodio` siempre corresponde al mismo
        `(id_paciente, fecha_ancla)` (ver `pseudonimizacion/claves.py::
        generar_id_episodio`), así que un insert-si-no-existe es seguro.
        """
        with Session(self._engine) as sesion, sesion.begin():
            if sesion.get(Episodio, id_episodio) is not None:
                return
            sesion.add(Episodio(id_episodio=id_episodio, id_paciente=id_paciente, fecha_ancla=fecha_ancla))

    # --- registro anonimizado: dispatch por tipo_documento -------------------

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        if registro.tipo_documento is TipoDocumento.LABORATORIO:
            self._escribir_laboratorio(registro)
        elif registro.tipo_documento is TipoDocumento.ECG:
            self._escribir_ecg(registro)
        elif registro.tipo_documento is TipoDocumento.ECOCARDIOGRAMA:
            self._escribir_eco(registro)
        else:
            raise ValueError(f"tipo_documento no soportado por EscritorPostgres: {registro.tipo_documento!r}")

    def _escribir_laboratorio(self, registro: RegistroAnonimizado) -> None:
        contenido: ContenidoLaboratorioSalida = registro.contenido
        with Session(self._engine) as sesion, sesion.begin():
            for fila in contenido.resultados:
                sesion.add(
                    ResultadoLaboratorio(
                        id_episodio=registro.id_episodio,
                        id_medico=contenido.id_medico,
                        analito=fila.analito,
                        seccion=fila.seccion,
                        valor_num=fila.valor_num,
                        valor_texto=fila.valor_texto,
                        unidad=fila.unidad,
                        ref_min=fila.ref_min,
                        ref_max=fila.ref_max,
                    )
                )

    def _escribir_ecg(self, registro: RegistroAnonimizado) -> None:
        contenido: ContenidoEcgSalida = registro.contenido
        with Session(self._engine) as sesion, sesion.begin():
            sesion.add(
                MedicionEcg(
                    id_episodio=registro.id_episodio,
                    id_medico=contenido.id_medico,
                    vent_rate=contenido.vent_rate,
                    pr_interval=contenido.pr_interval,
                    qrs_duration=contenido.qrs_duration,
                    qt_qtc=contenido.qt_qtc,
                    ejes=contenido.ejes,
                    adicionales=dict(registro.adicionales) or None,
                )
            )

    def _escribir_eco(self, registro: RegistroAnonimizado) -> None:
        contenido: ContenidoEcoSalida = registro.contenido

        columnas_ancha: dict[str, str] = {}
        unidades: dict[str, str] = {}
        extras: dict[str, str] = {}
        for medida in contenido.medidas:
            columna = _PIVOTE_MEDIDAS_ECO.get(medida.nombre.strip().upper())
            if columna is None:
                extras[medida.nombre] = medida.valor
                continue
            columnas_ancha[columna] = medida.valor
            if medida.unidad:
                unidades[columna] = medida.unidad

        with Session(self._engine) as sesion, sesion.begin():
            sesion.add(
                MedicionEco(
                    id_episodio=registro.id_episodio,
                    id_medico_solicitante=contenido.id_medico_solicitante,
                    id_medico_informante=contenido.id_medico_informante,
                    id_matricula_informante=contenido.id_matricula_informante,
                    unidades=unidades or None,
                    adicionales=extras or None,
                    **columnas_ancha,
                )
            )
            for seccion in contenido.secciones_texto:
                sesion.add(
                    TextoSeccionEco(
                        id_episodio=registro.id_episodio, seccion=seccion.nombre, texto=seccion.texto
                    )
                )
